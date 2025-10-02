# probe.py
"""
Real-Time Network Probe
- Run once: python probe.py --once
- Run continuously: python probe.py --interval 1   (interval in minutes)
"""

import subprocess, sys, platform, re, time, argparse, os, json, sqlite3, csv, logging
from datetime import datetime
from time import perf_counter
import requests
import threading

# Try to import push_row helper (optional). If not present, probe still works locally.
try:
    from push_row import push_row
except Exception:
    push_row = None

# Load local .env when present (optional convenience)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# === CONFIG (edit hosts here) ===
ENDPOINTS = [
    {"name": "Google DNS", "host": "8.8.8.8", "prefer": "icmp"},
    {"name": "Google", "host": "www.google.com", "prefer": "http"},
    {"name": "Yahoo", "host": "www.yahoo.com", "prefer": "http"},
    {"name": "Bing", "host": "www.bing.com", "prefer": "http"},
    {"name": "Cloudflare DNS", "host": "1.1.1.1", "prefer": "icmp"},
]


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "metrics.db")
CSV_PATH = os.path.join(DATA_DIR, "probes.csv")
LOG_PATH = os.path.join(DATA_DIR, "probe.log")

LATENCY_ALERT_MS = 200   # alert threshold
PACKET_LOSS_ALERT_PCT = 20.0

PING_COUNT = 4
PING_TIMEOUT_MS = 1000  # per-packet timeout for Windows ping -w (ms)

# === logging ===
os.makedirs(DATA_DIR, exist_ok=True)
logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
                    format="%(asctime)s %(levelname)s: %(message)s")
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)

# === DB helpers ===
def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=30)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS probes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        name TEXT,
        host TEXT,
        method TEXT,
        avg_ms REAL,
        min_ms REAL,
        max_ms REAL,
        rtts TEXT,
        sent INTEGER,
        received INTEGER,
        packet_loss_pct REAL,
        http_status INTEGER,
        error TEXT
    );
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        name TEXT,
        host TEXT,
        metric TEXT,
        value REAL,
        threshold REAL,
        message TEXT
    );
    """)
    conn.commit()
    conn.close()

# === ping (Windows-friendly parsing) ===
def run_ping(host, count=PING_COUNT, timeout_ms=PING_TIMEOUT_MS):
    is_win = platform.system().lower().startswith("win")
    if is_win:
        cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    else:
        # fallback for other OS
        cmd = ["ping", "-c", str(count), "-W", str(int(timeout_ms/1000)), host]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=(count * (timeout_ms/1000.0) + 5))
        out = proc.stdout + proc.stderr
    except Exception as e:
        return {"sent": count, "received": 0, "packet_loss_pct": 100.0, "rtts": [], "avg_ms": None, "min_ms": None, "max_ms": None, "raw_output": str(e)}

    # collect rtt values like: "time=14ms" or "time<1ms"
    rtt_matches = re.findall(r"time[=<]\s*(\d+)\s*ms", out)
    rtts = [int(x) for x in rtt_matches] if rtt_matches else []

    # packets summary (Windows style)
    sent = received = lost = None
    loss_pct = None
    m = re.search(r"Packets: Sent = (\d+), Received = (\d+), Lost = (\d+)\s*\((\d+)% loss\)", out)
    if m:
        sent = int(m.group(1)); received = int(m.group(2)); lost = int(m.group(3)); loss_pct = float(m.group(4))
    else:
        # try Linux/other format
        m2 = re.search(r"(\d+)\s+packets transmitted\,\s+(\d+)\s+received\,.*?(\d+\.?\d*)\% packet loss", out)
        if m2:
            sent = int(m2.group(1)); received = int(m2.group(2)); loss_pct = float(m2.group(3))
            lost = sent - received

    avg_ms = min_ms = max_ms = None
    if rtts:
        avg_ms = float(sum(rtts)/len(rtts))
        min_ms = float(min(rtts))
        max_ms = float(max(rtts))

    # fallback if packet count parse failed:
    if sent is None:
        sent = count
        received = len(rtts)
        lost = sent - received
        loss_pct = (lost / sent) * 100.0

    return {
        "sent": sent,
        "received": received,
        "packet_loss_pct": float(loss_pct if loss_pct is not None else 100.0),
        "rtts": rtts,
        "avg_ms": avg_ms,
        "min_ms": min_ms,
        "max_ms": max_ms,
        "raw_output": out
    }

# === simple HTTP probe fallback ===
def run_http(host, timeout_s=3):
    if not host.startswith("http://") and not host.startswith("https://"):
        url = "https://" + host
    else:
        url = host
    try:
        t0 = perf_counter()
        r = requests.get(url, timeout=timeout_s)
        elapsed = (perf_counter() - t0) * 1000.0
        return {"avg_ms": float(elapsed), "http_status": r.status_code, "error": None}
    except Exception as e:
        return {"avg_ms": None, "http_status": None, "error": str(e)}

# === write to CSV & DB ===
CSV_HEADERS = ["timestamp","name","host","method","avg_ms","min_ms","max_ms","rtts","sent","received","packet_loss_pct","http_status","error"]

def append_csv(row, csv_path=CSV_PATH):
    write_header = not os.path.exists(csv_path)
    with open(csv_path, "a", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(CSV_HEADERS)
        writer.writerow([row.get(h, "") for h in CSV_HEADERS])

def insert_db(row, db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=30)
    c = conn.cursor()
    c.execute("""INSERT INTO probes (timestamp,name,host,method,avg_ms,min_ms,max_ms,rtts,sent,received,packet_loss_pct,http_status,error)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (row['timestamp'], row['name'], row['host'], row['method'], row['avg_ms'], row['min_ms'], row['max_ms'],
               json.dumps(row['rtts']), row['sent'], row['received'], row['packet_loss_pct'], row.get('http_status'), row.get('error')))
    conn.commit()
    conn.close()

def insert_alert(alert, db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=30)
    c = conn.cursor()
    c.execute("""INSERT INTO alerts (timestamp, name, host, metric, value, threshold, message) VALUES (?,?,?,?,?,?,?)""",
              (alert['timestamp'], alert['name'], alert['host'], alert['metric'], alert['value'], alert['threshold'], alert['message']))
    conn.commit()
    conn.close()

# === helper: push to cloud asynchronously ===
def push_to_cloud_async(payload):
    if not push_row:
        # no push helper available
        return
    def _worker(p):
        try:
            push_row(p)
            logging.info("Pushed row to cloud /ingest")
        except Exception as e:
            logging.debug(f"Cloud push failed (ignored): {e}")
    t = threading.Thread(target=_worker, args=(payload,), daemon=True)
    t.start()

# === per-host probe run ===
def probe_one(endpoint):
    name = endpoint.get("name")
    host = endpoint.get("host")
    prefer = endpoint.get("prefer", "icmp")  # "icmp" or "http"
    ts = datetime.utcnow().isoformat() + "Z"
    row = {
        "timestamp": ts, "name": name, "host": host, "method": None,
        "avg_ms": None, "min_ms": None, "max_ms": None, "rtts": [],
        "sent": None, "received": None, "packet_loss_pct": None, "http_status": None, "error": None
    }

    # Try ICMP ping unless prefer=http
    if prefer != "http":
        ping_result = run_ping(host)
        row.update({
            "method": "icmp",
            "avg_ms": ping_result.get("avg_ms"),
            "min_ms": ping_result.get("min_ms"),
            "max_ms": ping_result.get("max_ms"),
            "rtts": ping_result.get("rtts"),
            "sent": ping_result.get("sent"),
            "received": ping_result.get("received"),
            "packet_loss_pct": ping_result.get("packet_loss_pct"),
            "error": None
        })
        # If everything lost (100%), try HTTP fallback
        if row['packet_loss_pct'] >= 100.0:
            http_result = run_http(host)
            row.update({
                "method": "http",
                "avg_ms": http_result.get("avg_ms"),
                "http_status": http_result.get("http_status"),
                "error": http_result.get("error")
            })
    else:
        # prefer http
        http_result = run_http(host)
        row.update({
            "method": "http",
            "avg_ms": http_result.get("avg_ms"),
            "http_status": http_result.get("http_status"),
            "error": http_result.get("error")
        })
        # still try ping in background to collect packet loss if possible
        ping_result = run_ping(host)
        row['sent'] = ping_result.get("sent")
        row['received'] = ping_result.get("received")
        row['packet_loss_pct'] = ping_result.get("packet_loss_pct")
        if not row['min_ms'] and ping_result.get("min_ms"):
            row['min_ms'] = ping_result.get("min_ms")
            row['max_ms'] = ping_result.get("max_ms")
            if ping_result.get("rtts"):
                row['rtts'] = ping_result.get("rtts")

    return row

# === check alerts ===
def check_and_record_alerts(row):
    alerts = []
    ts = row['timestamp']
    if row.get('avg_ms') is not None and row['avg_ms'] > LATENCY_ALERT_MS:
        alerts.append({
            "timestamp": ts, "name": row['name'], "host": row['host'],
            "metric": "latency_ms", "value": row['avg_ms'], "threshold": LATENCY_ALERT_MS,
            "message": f"High latency {row['avg_ms']:.1f} ms > {LATENCY_ALERT_MS} ms"
        })
    if row.get('packet_loss_pct') is not None and row['packet_loss_pct'] >= PACKET_LOSS_ALERT_PCT:
        alerts.append({
            "timestamp": ts, "name": row['name'], "host": row['host'],
            "metric": "packet_loss_pct", "value": row['packet_loss_pct'], "threshold": PACKET_LOSS_ALERT_PCT,
            "message": f"High packet loss {row['packet_loss_pct']:.1f}% >= {PACKET_LOSS_ALERT_PCT}%"
        })
    if (row.get('received') is not None and row['received'] == 0) and (row.get('http_status') is None):
        alerts.append({
            "timestamp": ts, "name": row['name'], "host": row['host'],
            "metric": "unreachable", "value": 1, "threshold": 0,
            "message": f"No responses from host"
        })

    for a in alerts:
        logging.warning(f"ALERT: {a['host']} {a['message']}")
        insert_alert(a)
    return alerts

# === run all endpoints and persist ===
def run_once():
    init_db()
    for ep in ENDPOINTS:
        logging.info(f"Probing {ep['name']} ({ep['host']}) ...")
        row = probe_one(ep)
        # ensure some types serializable
        row['rtts'] = row.get('rtts') or []
        append_csv(row)
        insert_db(row)
        check_and_record_alerts(row)
        logging.info(f"Recorded: host={row['host']} method={row['method']} avg_ms={row['avg_ms']} loss={row['packet_loss_pct']}")

        # Asynchronously push row to cloud (safe - doesn't crash the monitor)
        try:
            payload = {
                "timestamp": row["timestamp"],
                "name": row["name"],
                "host": row["host"],
                "method": row["method"],
                "avg_ms": row["avg_ms"],
                "min_ms": row["min_ms"],
                "max_ms": row["max_ms"],
                "rtts": row["rtts"],
                "sent": row["sent"],
                "received": row["received"],
                "packet_loss_pct": row["packet_loss_pct"],
                "http_status": row.get("http_status"),
                "error": row.get("error")
            }
            push_to_cloud_async(payload)
        except Exception as e:
            logging.debug("Failed to queue cloud push (ignored): %s", e)

# === CLI ===
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=1, help="Interval minutes (continuous mode). Default 1")
    args = parser.parse_args()

    if args.once:
        run_once()
        return

    logging.info(f"Starting continuous probe (every {args.interval} minute(s)). Ctrl+C to stop.")
    try:
        while True:
            start = perf_counter()
            run_once()
            elapsed = perf_counter() - start
            sleep_for = max(0, args.interval * 60 - elapsed)
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        logging.info("Stopping by user request.")
        sys.exit(0)

if __name__ == "__main__":
    main()
