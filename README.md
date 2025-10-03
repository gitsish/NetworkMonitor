# Network Monitor Dashboard — `network-probe--api`

## Executive summary
Network Monitor Dashboard is a compact, full-stack observability prototype that runs deterministic synthetic probes (ICMP and HTTP), persists measurements, and exposes live and historical telemetry through an interactive visualization layer. The implementation demonstrates system design decisions for reliable telemetry generation, durable storage, operational deployment, and scalable extension paths for production-grade monitoring.

---

## Problem statement
Modern distributed applications require continuous, low-overhead synthetic monitoring to detect network degradation (increased latency, packet loss, intermittent timeouts) prior to user-facing failures. Many lightweight monitoring solutions lack durable, queryable history or convenient capabilities for incident replay and geo-contextual analysis. This project addresses that gap by producing reproducible network telemetry, retaining it for analysis, and providing focused visualizations for rapid triage.

---

## Objective / statement of purpose
- Generate deterministic probe telemetry (ICMP and HTTP) with configurable sampling characteristics.  
- Persist probe events in a structured store to enable fast forensic queries and historical playback.  
- Provide a minimal, interactive visualization layer for live triage and incident reconstruction.  
- Keep the system lightweight and deployable to managed platforms with minimal operational friction.

---

## System overview
Three primary layers:

1. **Probe runners (ingestion)** — Periodic workers performing ICMP and HTTP checks. Emit structured rows: timestamp, target, probe type, latency, status, and metadata.  
2. **Persistence layer** — Pluggable storage abstraction (Supabase/Postgres or SQLite) with a canonical probe table for simple, performant queries.  
3. **Visualization & UI** — Streamlit dashboard providing live view, time-series, heatmaps, historical playback and optional globe/geolocation visualizations (loaded lazily).

---

## Current implementation status
- Telemetry recorded: **447 rows** (representative dataset used for UI validation and playback).  
- Implemented features:
  - ICMP + HTTP probes with configurable interval and timeout parameters.
  - Pluggable persistence layer (Supabase / SQLite).
  - Streamlit dashboard with live streaming view, timeline charts, heatmaps, CSV import/backfill, and optional globe visualization.
  - Deployment artifacts: `Procfile` and guidance for managed hosts.

---

## Screenshots & technical explanations

> The screenshots below are included to demonstrate core flows: detection, playback, geo-context, and forensic row inspection. Each image is annotated with what to inspect and why it matters for system evaluation.

### 1) Overview / Landing (summary & live snapshot)
<p align="center">
  <img width="100%" src="https://github.com/user-attachments/assets/4214a5dc-c7f9-4bea-b79f-93c5b82a3fb1" alt="Overview dashboard — summary cards and latest probe snapshot"/>
</p>

**What to inspect**
- Top summary cards (throughput, error rate, mean latency): confirm basic aggregations are computed server-side from canonical rows.  
- Latest probe snapshot stream: demonstrates low-latency ingestion → UI surface propagation.  
- Importance: verifies live ingestion pipeline and that the UI can render aggregates without heavy preprocessing.

---

### 2) Timeline & Playback (time-series)
<p align="center">
  <img width="48%" src="https://github.com/user-attachments/assets/80bd9e9c-ee34-4548-8d28-a2e081580064" alt="Latency timeline and playback controls"/>
  <img width="48%" src="https://github.com/user-attachments/assets/d42cf5e7-926c-4166-ae7c-9763ba908c9f" alt="Playback window and time slider"/>
</p>

**What to inspect**
- Multi-host latency timelines: verify per-target series rendering and alignment on the shared time axis.  
- Playback controls and selected time window: demonstrates ability to replay historical windows to reproduce incidents.  
- Importance: confirms the UI supports incident reconstruction and time-windowed queries for forensic analysis.

---

### 3) Heatmap (latency distribution)
<p align="center">
  <img width="48%" src="https://github.com/user-attachments/assets/5fca7298-ea87-4ec2-adf9-08cc99c3a43f" alt="Latency heatmap across targets and time windows"/>
  <img width="48%" src="https://github.com/user-attachments/assets/4c280ec3-5def-484a-a0da-c623cf9047af" alt="Heatmap zoom for outlier detection"/>
</p>

**What to inspect**
- Heatmap color scale: confirms aggregation binning (e.g., p50/p95 latency groups) and outlier visibility.  
- Row/column ordering: check grouping by host or by time window for fast anomaly spotting.  
- Importance: heatmaps condense large volumes of telemetry into high-density anomaly indicators.

---

### 4) Globe / Geo Context (optional module)
<p align="center">
  <img width="48%" src="https://github.com/user-attachments/assets/807fd976-e89d-4e6a-b06b-57bda551840f" alt="Globe visualization — regional latency patterns"/>
  <img width="48%" src="https://github.com/user-attachments/assets/41ab96e4-3623-42b3-a2af-7cf9f28e935b" alt="Globe with probe origin overlays"/>
</p>

**What to inspect**
- Geographic clustering of latency or packet loss: look for regional concentrations indicating ISP or routing issues.  
- Lazy-load behavior: globe is an optional visualization loaded on demand to avoid import-time failures (operational design choice).  
- Importance: provides geo context for distributed incident analysis without forcing heavy dependencies at startup.

---

### 5) Detailed row view & metadata (forensics)
<p align="center">
  <img width="95%" src="https://github.com/user-attachments/assets/ab073258-1ff9-418d-ab60-b20437c46f53" alt="Detailed row viewer showing probe metadata and raw payload"/>
</p>

**What to inspect**
- Raw payload and metadata fields (HTTP status, headers, RTT): verify that probe metadata is preserved for forensic queries.  
- Identifiers and timestamps: confirm canonical row keys and UTC timestamps for correlation with other logs.  
- Importance: raw payloads are necessary for reproducing and diagnosing complex, transient issues.

---

## Data model (canonical row)
- `id` (unique)  
- `timestamp` (UTC)  
- `target` (hostname or URL)  
- `type` (`icmp` | `http`)  
- `latency_ms` (float)  
- `status` (`success` | `timeout` | `error`)  
- `metadata` (JSON — e.g., HTTP status, headers)  
- `origin` (optional — probe origin/location)

---

## Design rationale & constraints
- **Compact schema** reduces query complexity and simplifies backfills and partitioning.  
- **Separation of ingestion and visualization** allows independent scaling of probe workers and the UI.  
- **Lazy-loading heavy visuals** mitigates deployment-time failures and reduces initial resource needs.  
- **Pluggable persistence** enables local demos (SQLite) and production deployments (Supabase/Postgres).

---

## Feasibility and scalability
**Operational feasibility**: probe workers are network-bound and CPU-light; a single modern VM can run hundreds of low-frequency probes.  
**Scaling path**:
- Ingestion: containerize probe workers; use a message broker (Kafka/RabbitMQ) for buffering and partitioning.  
- Storage: migrate to a time-series back-end (TimescaleDB/InfluxDB) or partitioned Postgres with retention policies.  
- UI: provide an API layer, use SSE/WebSocket for push updates, and offload heavy aggregations to async workers with caching (Redis).

---

## Prioritized roadmap (next features)
1. Alerting & rule engine (webhook integrations).  
2. Time-series backend migration (TimescaleDB/InfluxDB).  
3. Distributed edge probes (geographic agents).  
4. Low-latency push API (SSE/WebSocket) for real-time dashboards.  
5. Anomaly detection (statistical baselining / EWMA).  
6. Multi-tenant views and RBAC for enterprise deployment.

---

## Reliability & operational notes
- **Backpressure**: support batching and a message broker for higher ingest loads.  
- **Observability**: instrument probe workers and storage layer with metrics (counts, latencies, error rates) and alerts.  
- **Security**: store secrets in environment/secret stores; sanitize any collected metadata that may contain sensitive information.

---

## Testing & validation
- Unit tests for parsing and storage adapters.  
- Integration tests validating probe → persistence → visualization paths using synthetic targets.  
- Load tests to validate ingestion throughput and retention behavior.

---

## Conclusion
This repository demonstrates a pragmatic approach to synthetic network monitoring: deterministic probe generation, a compact canonical data model for durable storage, and focused visual surfaces for triage and forensic playback. The attached screenshots provide direct evidence of ingestion, analysis, and geo-context capabilities. The project is a production-feasible prototype and includes a clear extension plan for scaling to higher volume, multi-tenant, and alerting use cases.

---

**Status:** proof-of-concept with persistent telemetry (447 rows) and documented production extension paths.  
**Contact:** Aaisha — `gaaisha05@gmail.com` • https://github.com/gitsish
