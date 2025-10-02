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
import streamlit.components.v1 as components
import json, random

# -----------------------------
# Load .env (for local dev)
# -----------------------------
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

# -----------------------------
# Sidebar
# -----------------------------
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
# Globe background injection
# -----------------------------
DEFAULT_STYLE = """
<style>
  #globeViz {
    position: fixed;
    top: 0; left: 0;
    width: 100vw; height: 100vh;
    z-index: -1;
    opacity: 0.45;
    pointer-events: none;
    background: radial-gradient(ellipse at center, rgba(0,0,0,0.0) 0%, rgba(0,0,0,0.18) 100%);
  }
  .stApp > .main { position: relative; z-index: 1; }
  .css-1d391kg, .css-1l9bzkb { z-index: 2; position: relative; }
</style>
"""

SCRIPT_TEMPLATE = """
<script src="https://unpkg.com/three@0.159.0/build/three.min.js"></script>
<script src="https://unpkg.com/globe.gl"></script>
<script>
(function() {
  const nodes = [];
  const arcs = [];

  setTimeout(() => {
    const container = document.getElementById('globeViz');
    if (!container) return;

    const G = Globe()(container)
      .globeImageUrl('//unpkg.com/three-globe/example/img/earth-night.jpg')
      .backgroundImageUrl('//unpkg.com/three-globe/example/img/night-sky.png')
      .showGraticules(false)
      .pointsData(nodes)
      .pointAltitude(d => d.size || 0.4)
      .pointColor(d => d.color || 'white')
      .pointRadius(0.6)
      .arcsData(arcs)
      .arcColor(d => d.color || 'rgba(0,200,255,0.6)')
      .arcAltitude(d => d.altitude || 0.06)
      .arcStroke(0.8)
      .arcDashLength(0.4)
      .arcDashGap(0.2)
      .arcDashAnimateTime(1500);

    G.controls().autoRotate = true;
    G.controls().autoRotateSpeed = 0.9;

    setInterval(() => {
      G.arcsData(arcs.map(a => ({ ...a, arcDashInitialGap: Math.random() })));
    }, 2500);
  }, 400);
})();
</script>
"""

full_html = f"""
{DEFAULT_STYLE}
<div id="globeViz"></div>
{SCRIPT_TEMPLATE}
"""
components.html(full_html, height=600, scrolling=False)

# -----------------------------
# Data loader
# -----------------------------
@st.cache_data(ttl=10)
def load_data(limit=2000, use_csv_local=False, csv_path_local=None, db_path_local=None):
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

        if "ts" in df.columns: df = df.rename(columns={"ts": "timestamp"})
        if "latency_ms" in df.columns: df = df.rename(columns={"latency_ms": "avg_ms"})
        if "loss_pct" in df.columns: df = df.rename(columns={"loss_pct": "packet_loss_pct"})

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        return df
    except Exception:
        try:
            if use_csv_local and csv_path_local and os.path.exists(csv_path_local):
                return pd.read_csv(csv_path_local, parse_dates=["timestamp"])
            if db_path_local and os.path.exists(db_path_local):
                conn = sqlite3.connect(db_path_local)
                df = pd.read_sql("SELECT * FROM probes ORDER BY timestamp ASC", conn, parse_dates=["timestamp"])
                conn.close()
                return df
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

# -----------------------------
# Load & filter data
# -----------------------------
df = load_data(use_csv_local=use_csv, csv_path_local=csv_path, db_path_local=db_path)

if df.empty:
    st.warning("⚠️ No data available. API unreachable and no local data found.")
    st.stop()

now = datetime.now(timezone.utc)
start_time = now - timedelta(hours=hours)
df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
df = df[df["timestamp"] >= start_time]

all_hosts = sorted(df["host"].unique())
hosts_selected = st.sidebar.multiselect("Hosts to show", options=all_hosts, default=all_hosts)
if not hosts_selected:
    st.warning("Select at least one host to display.")
    st.stop()
filtered = df[df["host"].isin(hosts_selected)]

# -----------------------------
# Metrics
# -----------------------------
st.markdown("## Uptime & Latest metrics")
cols = st.columns(len(hosts_selected))
for i, host in enumerate(hosts_selected):
    sub = filtered[filtered["host"] == host]
    total = len(sub)
    if total == 0:
        uptime_pct, latency_display, loss_display, proto = 0, "n/a", "n/a", "n/a"
    else:
        if "packet_loss_pct" in sub.columns:
            up = len(sub[sub["packet_loss_pct"] < 100])
        else:
            up = len(sub[pd.notnull(sub.get("avg_ms"))])
        uptime_pct = (up / total * 100.0) if total else 0.0

        last = sub.sort_values("timestamp").iloc[-1]
        latency_display = f"{last['avg_ms']:.1f} ms" if pd.notnull(last.get("avg_ms")) else "n/a"
        loss_display = f"{last['packet_loss_pct']:.1f}%" if pd.notnull(last.get("packet_loss_pct")) else "n/a"
        proto = last.get("protocol") or last.get("method") or "n/a"

    with cols[i]:
        st.metric(f"{host} uptime % (last {hours}h)", f"{uptime_pct:.1f}%")
        st.caption(f"Last: {proto} | Latency: {latency_display} | Loss: {loss_display}")

# -----------------------------
# Charts
# -----------------------------
st.markdown("---")
st.markdown("## Time series")

if not filtered.empty:
    if "avg_ms" in filtered.columns:
        lat_chart = (
            alt.Chart(filtered.dropna(subset=["avg_ms"]))
            .mark_line()
            .encode(
                x="timestamp:T",
                y="avg_ms:Q",
                color="host:N",
                tooltip=["timestamp:T", "host:N", "avg_ms:Q", "packet_loss_pct:Q"],
            )
            .interactive()
            .properties(height=300)
        )
        st.altair_chart(lat_chart, use_container_width=True)

    if "packet_loss_pct" in filtered.columns:
        loss_chart = (
            alt.Chart(filtered.dropna(subset=["packet_loss_pct"]))
            .mark_line()
            .encode(
                x="timestamp:T",
                y="packet_loss_pct:Q",
                color="host:N",
                tooltip=["timestamp:T", "host:N", "packet_loss_pct:Q", "avg_ms:Q"],
            )
            .interactive()
            .properties(height=300)
        )
        st.altair_chart(loss_chart, use_container_width=True)

# -----------------------------
# Alerts
# -----------------------------
st.markdown("---")
st.markdown("## Alerts (detected)")

alerts = []
for _, row in filtered.iterrows():
    if pd.notnull(row.get("avg_ms")) and row["avg_ms"] > LATENCY_ALERT_MS:
        alerts.append({"timestamp": row["timestamp"], "host": row["host"], "msg": f"High latency > {LATENCY_ALERT_MS} ms"})
    if pd.notnull(row.get("packet_loss_pct")) and row["packet_loss_pct"] >= PACKET_LOSS_ALERT_PCT:
        alerts.append({"timestamp": row["timestamp"], "host": row["host"], "msg": f"High packet loss >= {PACKET_LOSS_ALERT_PCT}%"})

if alerts:
    st.dataframe(pd.DataFrame(alerts).sort_values("timestamp", ascending=False))
else:
    st.info("No alerts in selected timeframe.")

# -----------------------------
# On-demand Probe
# -----------------------------
st.markdown("---")
st.subheader("🕹️ Probe a Site Now")

url = st.text_input("Enter a website or IP (e.g., www.google.com, 8.8.8.8):")
if st.button("Probe (HTTP direct)"):
    if url:
        try:
            start = datetime.utcnow().timestamp()
            r = requests.get("http://" + url, timeout=5)
            latency = (datetime.utcnow().timestamp() - start) * 1000
            if latency < 200:
                st.success(f"🟢 {url} responded in {latency:.2f} ms (HTTP {r.status_code})")
            elif latency < 500:
                st.warning(f"🟡 {url} responded in {latency:.2f} ms (HTTP {r.status_code})")
            else:
                st.error(f"🔴 {url} responded in {latency:.2f} ms (HTTP {r.status_code})")
        except Exception as e:
            st.error(f"❌ Failed to probe {url}: {e}")

host_input = st.text_input("Enter host for cloud probe (default 1.1.1.1):", "1.1.1.1")
if st.button("Run Probe Now (cloud API)"):
    try:
        headers = {"Content-Type": "application/json"}
        if RUN_API_KEY:
            headers["X-API-KEY"] = RUN_API_KEY
        r = requests.post(f"{PROBE_API_BASE}/run?host={host_input}", headers=headers, timeout=6)
        r.raise_for_status()
        st.success(f"Triggered cloud probe for {host_input}: {r.json()}")
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Failed to trigger cloud probe: {e}")
