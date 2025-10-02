# globe_widget.py
# Small helper to render a Globe.gl background in Streamlit.
# Usage: from globe_widget import render_globe
#        render_globe(nodes, arcs, opacity=0.55, auto_rotate_speed=0.9, show_graticules=False)

import streamlit.components.v1 as components
import json
import random

DEFAULT_CSS = """
<style>
  /* Full-page globe container behind everything */
  #globeViz {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    z-index: -1;
    opacity: OPACITY_TOKEN;
    pointer-events: none;
    transition: opacity 0.35s ease;
    background: radial-gradient(ellipse at center, rgba(0,0,0,0.0) 0%, rgba(0,0,0,0.18) 100%);
  }

  /* make sure streamlit content sits above globe */
  .stApp > .main { position: relative; z-index: 1; }
  /* sidebar z-index fallback (Streamlit classes may vary across versions) */
  .css-1d391kg, .css-1l9bzkb { z-index: 2; position: relative; }
</style>
"""

# NOTE: Use token placeholders and do string replace (avoid .format with JS braces).
SCRIPT_TEMPLATE = """
<script src="https://unpkg.com/three@0.159.0/build/three.min.js"></script>
<script src="https://unpkg.com/globe.gl"></script>

<script>
(function() {
  const nodes = __NODES_JSON__;
  const arcs = __ARCS_JSON__;
  const showGraticules = __GRATICULE_TOKEN__;
  const autoRotateSpeed = __ROTATE_SPEED__;

  // delay slightly so Streamlit DOM has inserted the globe container
  setTimeout(() => {
    const container = document.getElementById('globeViz');
    if (!container) {
      console.warn('globe_widget: container missing');
      return;
    }

    const G = Globe()(container)
      .globeImageUrl('//unpkg.com/three-globe/example/img/earth-night.jpg')
      .backgroundImageUrl('//unpkg.com/three-globe/example/img/night-sky.png')
      .showGraticules(showGraticules)
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
    G.controls().autoRotateSpeed = autoRotateSpeed;

    // gentle periodic refresh to animate arcs
    setInterval(() => {
      G.arcsData(arcs.map(a => ({ ...a, arcDashInitialGap: Math.random() })));
    }, 2500);
  }, 350);
})();
</script>
"""

def _coerce_nodes(nodes):
    out = []
    for n in nodes or []:
        try:
            lat = float(n.get("lat", (random.random() - 0.5) * 180))
            lng = float(n.get("lng", (random.random() - 0.5) * 360))
        except Exception:
            lat = (random.random() - 0.5) * 180
            lng = (random.random() - 0.5) * 360
        out.append({
            "lat": lat,
            "lng": lng,
            "size": float(n.get("size", 0.5)),
            "color": n.get("color", "white"),
            "label": n.get("label", "")
        })
    return out

def _coerce_arcs(arcs):
    out = []
    for a in arcs or []:
        try:
            out.append({
                "startLat": float(a.get("startLat", 0)),
                "startLng": float(a.get("startLng", 0)),
                "endLat": float(a.get("endLat", 0)),
                "endLng": float(a.get("endLng", 0)),
                "color": a.get("color", "rgba(0,200,255,0.6)"),
                "altitude": float(a.get("altitude", 0.06))
            })
        except Exception:
            # skip malformed arc
            continue
    return out

def render_globe(nodes=None, arcs=None, opacity=0.55, auto_rotate_speed=12, show_graticules=False, height=700):
    """
    Render a Globe.gl background in Streamlit.

    - nodes: list of dicts {lat, lng, size, color, label}
    - arcs: list of dicts {startLat, startLng, endLat, endLng, color, altitude}
    - opacity: 0..1
    - auto_rotate_speed: float (0.2 slow → 2.0 fast)
    - show_graticules: boolean
    - height: pixel height for the generated component (recommended >= 600)
    """
    nodes = _coerce_nodes(nodes)
    arcs = _coerce_arcs(arcs)

    nodes_json = json.dumps(nodes)
    arcs_json = json.dumps(arcs)

    css = DEFAULT_CSS.replace("OPACITY_TOKEN", str(opacity))
    script = SCRIPT_TEMPLATE.replace("__NODES_JSON__", nodes_json)\
                            .replace("__ARCS_JSON__", arcs_json)\
                            .replace("__ROTATE_SPEED__", str(auto_rotate_speed))\
                            .replace("__GRATICULE_TOKEN__", "true" if show_graticules else "false")

    html = css + "<div id='globeViz'></div>" + script

    # Use components.html so it sits behind the Streamlit elements
    components.html(html, height=height, scrolling=False)
