# app.py
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timezone, timedelta
import altair as alt
import os
from dateutil.tz import tzutc

DEFAULT_DB = os.path.join("data", "metrics.db")
DEFAULT_CSV = os.path.join("data", "probes.csv")
LATENCY_ALERT_MS = 200
PACKET_LOSS_ALERT_PCT = 20.0

st.set_page_config(page_title="Real-Time Cloud Network Dashboard", layout="wide")

st.title("Real-Time Cloud Network Performance Dashboard")
st.sidebar.header("Data & Filters")

db_path = st.sidebar.text_input("SQLite DB path", DEFAULT_DB)
use_csv = st.sidebar.checkbox("Use CSV instead of DB (if checked, CSV path is used)", False)
csv_path = st.sidebar.text_input("CSV path", DEFAULT_CSV)

hours = st.sidebar.slider("Hours to show", min_value=1, max_value=168, value=24)
hosts_filter = st.sidebar.multiselect("Hosts to show (select below after data loads)", [])

st.sidebar.markdown("---")
st.sidebar.write("Alert thresholds (for display)")
st.sidebar.metric("Latency alert (ms)", LATENCY_ALERT_MS)
st.sidebar.metric("Packet loss alert (%)", PACKET_LOSS_ALERT_PCT)

@st.cache_data(ttl=10)
def load_data():
    if use_csv:
        if not os.path.exists(csv_path):
            return pd.DataFrame()
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    else:
        if not os.path.exists(db_path):
            return pd.DataFrame()
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("SELECT * FROM probes ORDER BY timestamp ASC", conn, parse_dates=["timestamp"])
        conn.close()
    # normalize columns
    if "rtts" in df.columns:
        # ensure rtts column is parsed
        try:
            df["rtts"] = df["rtts"].apply(lambda x: eval(x) if pd.notnull(x) and isinstance(x, str) else x)
        except Exception:
            pass
    return df

df = load_data()
if df.empty:
    st.warning("No data found. Run `python probe.py --once` first or check data paths.")
    st.stop()

now = datetime.now(timezone.utc)
start_time = now - timedelta(hours=hours)
df["timestamp"] = pd.to_datetime(df["timestamp"])
df = df[df["timestamp"] >= start_time]

# list hosts
all_hosts = sorted(df["host"].unique())
if not hosts_filter:
    hosts_filter = all_hosts[:]
hosts_to_show = st.multiselect("Select hosts to display", all_hosts, default=hosts_filter)

if not hosts_to_show:
    st.warning("Select at least one host to display.")
    st.stop()

filtered = df[df["host"].isin(hosts_to_show)].copy()

# summary metrics (uptime)
st.markdown("## Uptime & Latest metrics")
cols = st.columns(len(hosts_to_show))
for i, host in enumerate(hosts_to_show):
    sub = filtered[filtered["host"] == host]
    total = len(sub)
    up = len(sub[sub["received"] > 0]) if "received" in sub.columns else 0
    uptime_pct = (up / total * 100.0) if total > 0 else 0.0
    last = sub.sort_values("timestamp").iloc[-1] if total>0 else None
    latency_display = f"{last['avg_ms']:.1f} ms" if last is not None and pd.notnull(last.get("avg_ms")) else "n/a"
    loss_display = f"{last['packet_loss_pct']:.1f}%" if last is not None and pd.notnull(last.get("packet_loss_pct")) else "n/a"
    with cols[i]:
        st.metric(label=f"{host} uptime % (last {hours}h)", value=f"{uptime_pct:.1f}%")
        st.write(f"Last: {last['method'] if last is not None else 'n/a'} | Latency: {latency_display} | Loss: {loss_display}")

st.markdown("---")
st.markdown("## Time series")

# Latency chart
lat_chart = alt.Chart(filtered).mark_line().encode(
    x=alt.X("timestamp:T", title="Time (UTC)"),
    y=alt.Y("avg_ms:Q", title="Avg latency (ms)"),
    color="host:N",
    tooltip=["timestamp:T", "host:N", "avg_ms:Q", "packet_loss_pct:Q"]
).interactive().properties(height=300)

st.altair_chart(lat_chart, use_container_width=True)

# Packet loss chart
loss_chart = alt.Chart(filtered).mark_line().encode(
    x=alt.X("timestamp:T", title="Time (UTC)"),
    y=alt.Y("packet_loss_pct:Q", title="Packet loss (%)"),
    color="host:N",
    tooltip=["timestamp:T", "host:N", "packet_loss_pct:Q", "avg_ms:Q"]
).interactive().properties(height=300)

st.altair_chart(loss_chart, use_container_width=True)

st.markdown("---")
st.markdown("## Alerts (detected)")

# derived alerts from data
alerts = []
for _, row in filtered.iterrows():
    if pd.notnull(row.get("avg_ms")) and row["avg_ms"] > LATENCY_ALERT_MS:
        alerts.append({"timestamp": row["timestamp"], "host": row["host"], "metric": "latency_ms", "value": row["avg_ms"], "msg": f"High latency > {LATENCY_ALERT_MS} ms"})
    if pd.notnull(row.get("packet_loss_pct")) and row["packet_loss_pct"] >= PACKET_LOSS_ALERT_PCT:
        alerts.append({"timestamp": row["timestamp"], "host": row["host"], "metric": "packet_loss_pct", "value": row["packet_loss_pct"], "msg": f"High packet loss >= {PACKET_LOSS_ALERT_PCT}%"})
    if pd.notnull(row.get("received")) and row["received"] == 0 and pd.isnull(row.get("http_status")):
        alerts.append({"timestamp": row["timestamp"], "host": row["host"], "metric": "unreachable", "value": 1, "msg": "Host unreachable (no ICMP & no HTTP)"})

if alerts:
    a_df = pd.DataFrame(alerts).sort_values("timestamp", ascending=False)
    st.dataframe(a_df)
else:
    st.info("No alerts in selected timeframe.")

st.markdown("---")
st.write("Data source:", "CSV" if use_csv else "SQLite DB - " + db_path)
if st.button("Refresh data"):
    st.cache_data.clear()
    st.rerun()
# ------------------------------
# On-demand probing (user input)
# ------------------------------
import requests, socket, time

st.markdown("---")
st.subheader("🕹️ Probe a Site Now")

url = st.text_input("Enter a website or IP (e.g., www.google.com, 8.8.8.8):")

if st.button("Probe"):
    if url:
        with st.spinner(f"Probing {url}..."):
            try:
                start = time.time()
                # try HTTP probe
                r = requests.get("http://" + url, timeout=5)
                latency = (time.time() - start) * 1000

                if latency < 200:
                    st.success(f"🟢 {url} responded in {latency:.2f} ms (HTTP {r.status_code})")
                elif latency < 500:
                    st.warning(f"🟡 {url} responded in {latency:.2f} ms (HTTP {r.status_code})")
                else:
                    st.error(f"🔴 {url} responded in {latency:.2f} ms (HTTP {r.status_code})")

            except Exception as e:
                st.error(f"❌ Failed to probe {url}: {e}")
    else:
        st.warning("Please enter a valid host or website.")
