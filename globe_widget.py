# globe_widget.py
# Standalone Globe.gl embed for Streamlit.
# Usage: from globe_widget import render_globe; render_globe(nodes, arcs, height=520)

import streamlit as st
import json
import random

DEFAULT_STYLE = """
<style>
  /* Globe container sits behind the app content */
  #globeViz {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    z-index: -1;
    opacity: 0.90;           /* tweak for subtlety */
    pointer-events: none;    /* let clicks pass through */
    transition: opacity 0.4s ease;
    background: radial-gradient(ellipse at center, rgba(0,0,0,0.0) 0%, rgba(0,0,0,0.15) 100%);
  }
  /* keep app content above globe */
  .stApp > .main {
    position: relative;
    z-index: 1;
  }
  /* Keep streamlit sidebar above globe too */
  .css-1d391kg { z-index: 2; } /* fallback; class names may vary by Streamlit version */
</style>
"""

GLOBE_HTML_TEMPLATE = """
{style}
<div id="globeViz"></div>

<script src="https://unpkg.com/three@0.159.0/build/three.min.js"></script>
<script src="https://unpkg.com/globe.gl"></script>

<script>
(function() {{
  const nodes = {nodes_json};
  const arcs = {arcs_json};

  const G = Globe()(document.getElementById('globeViz'))
    .globeImageUrl('//unpkg.com/three-globe/example/img/earth-dark.jpg')
    .backgroundImageUrl('//unpkg.com/three-globe/example/img/night-sky.png')
    .showGraticules(false)
    .pointsData(nodes)
    .pointAltitude(d => d.size || 0.5)
    .pointColor(d => d.color || 'white')
    .pointRadius(0.6)
    .arcsData(arcs)
    .arcColor(d => d.color || 'rgba(0,200,255,0.6)')
    .arcAltitude(d => d.altitude || 0.08)
    .arcStroke(0.8)
    .arcDashLength(0.4)
    .arcDashGap(0.2)
    .arcDashInitialGap(() => Math.random())
    .arcDashAnimateTime(2000)
    .onPointClick(p => {{
       if (p && p.label) {{
         // when clicked (rare since pointer-events none), small hint
         alert(`Host: ${{p.label}}\\nAvg latency: ${{p.avg_latency ?? 'n/a'}} ms`);
       }}
    }});

  // subtle auto-rotation
  G.controls().autoRotate = true;
  G.controls().autoRotateSpeed = 12;

  // Make arcs animate in waves
  function regenArcs() {{
    G.arcsData(arcs.map(a => ({{
      ...a,
      arcDashInitialGap: Math.random()
    }})));
  }}
  setInterval(regenArcs, 3000);
}})();
</script>
"""

def _coerce_nodes(nodes):
    """Ensure nodes list is JSON-serializable and has sane defaults."""
    out = []
    for n in nodes:
        try:
            lat = float(n.get("lat", (random.random()-0.5)*180))
            lng = float(n.get("lng", (random.random()-0.5)*360))
        except Exception:
            lat = (random.random()-0.5)*180
            lng = (random.random()-0.5)*360
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
    for a in arcs:
        out.append({
            "startLat": float(a.get("startLat", 0)),
            "startLng": float(a.get("startLng", 0)),
            "endLat": float(a.get("endLat", 0)),
            "endLng": float(a.get("endLng", 0)),
            "color": a.get("color", "rgba(0,200,255,0.6)"),
            "altitude": float(a.get("altitude", 0.08))
        })
    return out

def render_globe(nodes=None, arcs=None, height=520):
    """
    Render globe in Streamlit.
      - nodes: list of {lat,lng,size,color,label,avg_latency}
      - arcs: list of {startLat,startLng,endLat,endLng,color,altitude}
    """
    nodes = nodes or []
    arcs = arcs or []
    nodes = _coerce_nodes(nodes)
    arcs = _coerce_arcs(arcs)
    nodes_json = json.dumps(nodes)
    arcs_json = json.dumps(arcs)
    html = GLOBE_HTML_TEMPLATE.format(style=DEFAULT_STYLE, nodes_json=nodes_json, arcs_json=arcs_json)
    components.html(html, height=height, scrolling=False)
