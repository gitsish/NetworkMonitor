# globe_component.py
import streamlit.components.v1 as components
import json, random, os, requests, time
from statistics import mean
from dateutil import parser as _dt_parser

# Optional: runner coordinates (set env vars in deployment for correct location)
RUNNER_LAT = float(os.getenv("RUNNER_LAT", "37.7749"))   # default SF
RUNNER_LNG = float(os.getenv("RUNNER_LNG", "-122.4194"))

# Manual mapping for well-known hosts
HOST_COORDS = {
    "1.1.1.1": {"lat": 33.4940, "lng": -117.1400},
    "8.8.8.8": {"lat": 37.751, "lng": -97.822},
    "www.google.com": {"lat": 37.422, "lng": -122.084},
    "www.bing.com": {"lat": 47.6097, "lng": -122.3331},
    "www.yahoo.com": {"lat": 37.7749, "lng": -122.4194},
}


_geoip_cache = {}
def try_geoip_lookup(host):
    """Try free GeoIP service for unknown IPs (cached)."""
    if host in _geoip_cache:
        return _geoip_cache[host]
    import re
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        try:
            r = requests.get(f"https://ipapi.co/{host}/json/", timeout=3)
            j = r.json()
            lat = j.get("latitude")
            lng = j.get("longitude")
            if lat and lng:
                coords = {"lat": float(lat), "lng": float(lng)}
                _geoip_cache[host] = coords
                return coords
        except Exception:
            pass
    _geoip_cache[host] = None
    return None


def render_globe(df):
    """Render an interactive globe with points and arcs based on probe data."""
    if df.empty:
        return

    # Normalize column names
    if "latency_ms" in df.columns and "avg_ms" not in df.columns:
        df = df.rename(columns={"latency_ms": "avg_ms"})

    # Compute stats per host
    host_stats = {}
    grouped = df.groupby("host")
    for host, g in grouped:
        latencies = g["avg_ms"].dropna().astype(float).tolist() if "avg_ms" in g else []
        loss_vals = g.get("packet_loss_pct", g.get("loss_pct"))
        loss_list = loss_vals.dropna().astype(float).tolist() if loss_vals is not None else []
        host_stats[host] = {
            "avg_latency": mean(latencies) if latencies else None,
            "latest_loss": (loss_list[-1] if loss_list else None),
            "count": len(g),
            "last_ts": str(g["timestamp"].max()) if "timestamp" in g.columns else None
        }

    # Build nodes
    nodes = []
    nodes.append({"lat": RUNNER_LAT, "lng": RUNNER_LNG, "size": 1.6, "color": "cyan", "label": "probe-runner"})
    for host, stats in host_stats.items():
        coords = HOST_COORDS.get(host) or try_geoip_lookup(host)
        if coords is None:
            coords = {"lat": (random.random() - 0.5) * 180, "lng": (random.random() - 0.5) * 360}
        size = 0.6 + min(2.0, 0.02 * (stats["count"] or 1))
        color = "orange" if stats.get("avg_latency") and stats["avg_latency"] > 300 else ("lime" if stats.get("avg_latency") and stats["avg_latency"] < 50 else "white")
        nodes.append({
            "lat": coords["lat"], "lng": coords["lng"], "size": size,
            "color": color, "label": host,
            "avg_latency": stats.get("avg_latency"),
            "count": stats.get("count"),
            "last_ts": stats.get("last_ts")
        })

    # Build arcs from runner to hosts
    arcs = []
    for n in nodes:
        if n.get("label") == "probe-runner":
            continue
        latency = n.get("avg_latency")
        arc_alt = min(0.5, 0.02 + (latency or 0) / 5000.0) if latency else 0.06
        col = "rgba(0,220,160,0.9)" if latency and latency < 100 else ("rgba(255,200,0,0.9)" if latency and latency < 400 else "rgba(255,40,60,0.95)")
        arcs.append({
            "startLat": RUNNER_LAT, "startLng": RUNNER_LNG,
            "endLat": n["lat"], "endLng": n["lng"],
            "color": col, "altitude": arc_alt,
            "label": n.get("label"), "latency": latency
        })

    nodes_json = json.dumps(nodes)
    arcs_json = json.dumps(arcs)

    globe_html = f"""
    <style>
      #globeViz {{
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
        z-index: -1; opacity: 0.6; pointer-events: none;
      }}
      .stApp > .main {{ position: relative; z-index: 1; }}
    </style>
    <div id="globeViz"></div>
    <script src="https://unpkg.com/three@0.159.0/build/three.min.js"></script>
    <script src="https://unpkg.com/globe.gl"></script>
    <script>
    (() => {{
      const nodes = {nodes_json};
      const arcs = {arcs_json};
      const G = Globe()(document.getElementById('globeViz'))
        .globeImageUrl('//unpkg.com/three-globe/example/img/earth-dark.jpg')
        .backgroundImageUrl('//unpkg.com/three-globe/example/img/night-sky.png')
        .showGlobe(true)
        .showGraticules(false)
        .pointsData(nodes)
        .pointAltitude(d => d.size)
        .pointColor(d => d.color)
        .pointRadius(0.7)
        .arcsData(arcs)
        .arcColor(d => d.color)
        .arcAltitude(d => d.altitude)
        .arcStroke(0.7)
        .arcDashLength(0.6)
        .arcDashGap(0.4)
        .arcDashAnimateTime(2000);
      G.controls().autoRotate = true;
      G.controls().autoRotateSpeed = 0.8;
    }})();
    </script>
    """
    components.html(globe_html, height=600)
