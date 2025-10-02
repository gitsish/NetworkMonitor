# app.py
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timezone, timedelta
import altair as alt
import os
import requests
from dotenv import load_dotenv
from dateutil import parser as _dt_parser
import random
from statistics import mean

# import the globe renderer
from globe_widget import render_globe

# Load local .env for dev
load_dotenv()

# -----------------------------
# Config / defaults
# -----------------------------
DEFAULT_DB = os.path.join("data", "metrics.db")
DEFAULT_CSV = os.path.join("data", "probes.csv")
LATENCY_ALERT_MS = 200
PACKET_LOSS_ALERT_PCT = 20.0

PROBE_API_BASE = os.getenv("PROBE_API_BASE", "https://web-production-d9ba8.up.railway.app")
RUN_API_KEY = os.getenv("RUN_API_KEY", "")

st.set_page_config(page_title="Real-Time Cloud Network Dashboard", layout="wide")
st.title("🌐 Real-Time Cloud Network Performance Dashboard")
st.sidebar.header("Data & Filters")

db_path = st.sidebar.text_input("SQLite DB path", DEFAULT_DB)
use_csv = st.sidebar.checkbox("Use CSV instead of DB (if checked, CSV path is used)", False)
csv_path = st.sidebar.text_input("CSV path", DEFAULT_CSV)
hours = st.sidebar.slider("Hours to show", min_value=1, max_value=168, value=24)

st.sidebar.markdown("---")
st.sidebar.write("Alert thresholds (for display)")
st.sidebar.metric("Latency alert (ms)", LATENCY_ALERT_MS)
st.sidebar.metric("Packet loss alert (%)", PACKET_LOSS_ALERT_PCT)

# -----------------------------
# Data loader
# -----------------------------
@st.cache_data(ttl=10)
def load_data(limit=5000, use_csv_local=False, csv_path_local=None, db_path_local=None):
    try:
        url = f"{PROBE_API_BASE}/data?limit={limit}"
        headers = {}
        if RUN_API_KEY:
            headers["X-API-KEY"] = RUN_API_KEY
        resp = requests.get(url, headers=headers, timeout=6)
        resp.raise_for_status()
        payload = resp.json().get("data", [])
        if not payload:
            return pd.DataFrame()
        df = pd.json_normalize(payload)

        # Normalize names
        if "ts" in df.columns: df.rename(columns={"ts": "timestamp"}, inplace=True)
        if "latency_ms" in df.columns: df.rename(columns={"latency_ms": "avg_ms"}, inplace=True)
        if "loss_pct" in df.columns: df.rename(columns={"loss_pct": "packet_loss_pct"}, inplace=True)

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")

        return df
    except Exception:
        # fallback to local
        try:
            if use_csv_local and csv_path_local and os.path.exists(csv_path_local):
                return pd.read_csv(csv_path_local, parse_dates=["timestamp"])
            if db_path_local and os.path.exists(db_path_local):
                conn = sqlite3.connect(db_path_local)
                df = pd.read_sql("SELECT * FROM probes ORDER BY timestamp ASC", conn, parse_dates=["timestamp"])
                conn.close()
                return df
        except Exception:
            pass
    return pd.DataFrame()

# load
df = load_data(use_csv_local=use_csv, csv_path_local=csv_path, db_path_local=db_path)

# If still empty, show message but continue (globe can still render)
if df.empty:
    st.warning("No data from cloud API and no local DB/CSV found. Add CSV or DB or fix PROBE_API_BASE.")
    st.stop()

# ensure timestamp exists and filter timeframe
if "timestamp" not in df.columns:
    st.error("Loaded data missing 'timestamp' column.")
    st.stop()

df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
now = datetime.now(timezone.utc)
start_time = now - timedelta(hours=hours)
df = df[df["timestamp"] >= start_time]

# Build host_stats
host_stats = {}
if not df.empty:
    grouped = df.groupby("host")
    for host, g in grouped:
        lat_list = g.get("avg_ms", pd.Series([], dtype=float)).dropna().astype(float).tolist()
        loss_series = g.get("packet_loss_pct")
        loss_list = []
        if loss_series is not None:
            try:
                loss_list = loss_series.dropna().astype(float).tolist()
            except Exception:
                loss_list = []
        host_stats[host] = {
            "avg_latency": mean(lat_list) if lat_list else None,
            "latest_loss": (loss_list[-1] if loss_list else None),
            "count": len(g),
            "last_ts": (g["timestamp"].max() if "timestamp" in g else None)
        }

# Manual geolocation mapping (add known hosts here)
HOST_COORDS = {
    "1.1.1.1": {"lat": 33.4940, "lng": -117.1400},
    "8.8.8.8": {"lat": 37.751, "lng": -97.822},
    "www.google.com": {"lat": 37.422, "lng": -122.084},
    "www.bing.com": {"lat": 47.6097, "lng": -122.3331},
    "www.yahoo.com": {"lat": 37.7749, "lng": -122.4194},
}

# GeoIP helper (best-effort; used only for IP-like hosts)
_geoip_cache = {}
def try_geoip_lookup(host):
    if host in _geoip_cache:
        return _geoip_cache[host]
    import re, time
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        try:
            r = requests.get(f"https://ipapi.co/{host}/json/", timeout=3)
            j = r.json()
            lat = j.get("latitude") or j.get("lat")
            lng = j.get("longitude") or j.get("lon")
            if lat and lng:
                coords = {"lat": float(lat), "lng": float(lng)}
                _geoip_cache[host] = coords
                time.sleep(0.05)
                return coords
        except Exception:
            pass
    _geoip_cache[host] = None
    return None

# Build globe nodes + arcs (runner at default SF unless env set)
RUNNER_LAT = float(os.getenv("RUNNER_LAT", "37.7749"))
RUNNER_LNG = float(os.getenv("RUNNER_LNG", "-122.4194"))

nodes = []
arcs = []
# add runner node (center/origin)
nodes.append({"lat": RUNNER_LAT, "lng": RUNNER_LNG, "size": 1.6, "color": "cyan", "label": "probe-runner"})

for host, stats in host_stats.items():
    coords = HOST_COORDS.get(host)
    if coords is None:
        coords = try_geoip_lookup(host)
    if coords is None:
        coords = {"lat": (random.random() - 0.5) * 180, "lng": (random.random() - 0.5) * 360}
    size = 0.5 + min(2.0, 0.02 * (stats.get("count", 1)))
    color = "orange" if stats.get("avg_latency") and stats["avg_latency"] > 300 else ("lime" if stats.get("avg_latency") and stats["avg_latency"] < 50 else "white")
    nodes.append({
        "lat": float(coords["lat"]),
        "lng": float(coords["lng"]),
        "size": size,
        "color": color,
        "label": host,
        "avg_latency": stats.get("avg_latency"),
        "count": stats.get("count")
    })
    arcs.append({
        "startLat": RUNNER_LAT, "startLng": RUNNER_LNG,
        "endLat": float(coords["lat"]), "endLng": float(coords["lng"]),
        "color": "rgba(0,200,255,0.6)",
        "altitude": 0.04 + (stats.get("avg_latency") or 0)/5000.0
    })

# Render the globe (imported helper)
# show_graticules True will draw latitude/longitude grid lines on the globe
render_globe(nodes=nodes, arcs=arcs, opacity=0.55, auto_rotate_speed=0.9, show_graticules=True, height=700)

# Now UI: hosts multiselect, metrics, charts, alerts (same as before)
all_hosts = sorted(df["host"].unique())
hosts_selected = st.sidebar.multiselect("Hosts to show (select which hosts to display)", options=all_hosts, default=all_hosts)
if not hosts_selected:
    st.warning("Select at least one host to display.")
    st.stop()

filtered = df[df["host"].isin(hosts_selected)].copy()
if filtered.empty:
    st.warning("No filtered data for the selected timeframe/hosts.")
    st.stop()

# Uptime & latest metrics
st.markdown("## Uptime & Latest metrics")
cols = st.columns(len(hosts_selected))
for i, host in enumerate(hosts_selected):
    sub = filtered[filtered["host"] == host]
    total = len(sub)
    if total == 0:
        uptime_pct = 0.0
        latency_display = "n/a"
        loss_display = "n/a"
        method_or_proto = "n/a"
    else:
        if "packet_loss_pct" in sub.columns:
            up = len(sub[sub["packet_loss_pct"] < 100])
        else:
            up = len(sub[pd.notnull(sub.get("avg_ms"))])
        uptime_pct = (up / total * 100.0) if total > 0 else 0.0
        last = sub.sort_values("timestamp").iloc[-1]
        latency_display = f"{last['avg_ms']:.1f} ms" if pd.notnull(last.get("avg_ms")) else "n/a"
        method_or_proto = last.get("protocol") or last.get("method") or "n/a"
        loss_val = last.get("packet_loss_pct") if "packet_loss_pct" in last else (last.get("loss_pct") if "loss_pct" in last else None)
        loss_display = f"{loss_val:.1f}%" if loss_val is not None and pd.notnull(loss_val) else "n/a"

    with cols[i]:
        st.metric(label=f"{host} uptime % (last {hours}h)", value=f"{uptime_pct:.1f}%")
        st.write(f"Last: {method_or_proto} | Latency: {latency_display} | Loss: {loss_display}")

# Charts (defensive: dropna on field that exists)
st.markdown("---")
st.markdown("## Time series")

if "avg_ms" in filtered.columns:
    tmp = filtered.dropna(subset=["avg_ms"])
    if not tmp.empty:
        lat_chart = (
            alt.Chart(tmp)
            .mark_line()
            .encode(x=alt.X("timestamp:T", title="Time (UTC)"),
                    y=alt.Y("avg_ms:Q", title="Avg latency (ms)"),
                    color="host:N",
                    tooltip=["timestamp:T", "host:N", "avg_ms:Q", "packet_loss_pct:Q"])
            .interactive()
            .properties(height=300)
        )
        st.altair_chart(lat_chart, use_container_width=True)

if "packet_loss_pct" in filtered.columns:
    tmp2 = filtered.dropna(subset=["packet_loss_pct"])
    if not tmp2.empty:
        loss_chart = (
            alt.Chart(tmp2)
            .mark_line()
            .encode(x=alt.X("timestamp:T", title="Time (UTC)"),
                    y=alt.Y("packet_loss_pct:Q", title="Packet loss (%)"),
                    color="host:N",
                    tooltip=["timestamp:T", "host:N", "packet_loss_pct:Q", "avg_ms:Q"])
            .interactive()
            .properties(height=300)
        )
        st.altair_chart(loss_chart, use_container_width=True)

# Alerts
st.markdown("---")
st.markdown("## Alerts (detected)")
alerts = []
for _, row in filtered.iterrows():
    if pd.notnull(row.get("avg_ms")) and row["avg_ms"] > LATENCY_ALERT_MS:
        alerts.append({"timestamp": row["timestamp"], "host": row["host"], "msg": f"High latency > {LATENCY_ALERT_MS} ms", "value": row["avg_ms"]})
    if pd.notnull(row.get("packet_loss_pct")) and row["packet_loss_pct"] >= PACKET_LOSS_ALERT_PCT:
        alerts.append({"timestamp": row["timestamp"], "host": row["host"], "msg": f"High packet loss >= {PACKET_LOSS_ALERT_PCT}%", "value": row["packet_loss_pct"]})

if alerts:
    st.dataframe(pd.DataFrame(alerts).sort_values("timestamp", ascending=False))
else:
    st.info("No alerts in selected timeframe.")

# Refresh button
st.markdown("---")
st.write("Data source:", "☁️ Cloud API" if PROBE_API_BASE else ("CSV" if use_csv else "SQLite DB - " + db_path))
if st.button("Refresh data"):
    st.cache_data.clear()
    st.rerun()
