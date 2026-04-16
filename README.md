# iag-jupyter

A self-contained Docker Compose environment that demonstrates **IBM Application Gateway (IAG) 25.12** acting as an HTTP reverse proxy with full WebSocket support, fronting two backends:

1. A custom Python WebSocket echo server (via nginx)
2. **JupyterLab** — with live kernel execution over WebSocket through IAG

All traffic is plain HTTP (no SSL required), making it easy to inspect and extend.

---

## Architecture

```
Browser / curl / test script
        │
        ▼  HTTP  port 9080
┌───────────────────────────┐
│   IBM Application Gateway  │  icr.io/ibmappgateway/ibm-application-gateway:25.12
│   (IAG / webseald)         │
│                             │
│  /jupyter/*  ──────────────┼──► jupyter:8888   (JupyterLab)
│  /*          ──────────────┼──► nginx:80        (WebSocket Demo)
└───────────────────────────┘          │
                                       ▼
                               ┌──────────────┐
                               │  nginx:alpine │  proxies /ws → ws-backend:8765
                               └──────┬───────┘
                                      │
                               ┌──────▼───────┐
                               │  ws-backend   │  Python WebSocket echo server
                               └──────────────┘

┌──────────────┐
│    statsd     │  UDP 8125 — receives IAG metrics (custom Python listener)
└──────────────┘
```

### Services

| Service | Image / Build | Internal Port | Host Port |
|---|---|---|---|
| `iag` | `icr.io/ibmappgateway/ibm-application-gateway:25.12` | 8080 | **9080** |
| `nginx` | `nginx:alpine` | 80 | **8080** (direct, bypasses IAG) |
| `ws-backend` | `./ws-backend` (Python 3.12) | 8765 | — |
| `jupyter` | `quay.io/jupyter/scipy-notebook:latest` | 8888 | — |
| `statsd` | `./statsd` (Python 3.12 Alpine) | 8125/udp | — |

---

## Prerequisites

- **Docker Desktop** 4.x or later (with Docker Compose v2 and buildx ≥ 0.17)
- **Python 3.x** (only needed to run the test script)
- No other local dependencies — all services run in containers

> **Apple Silicon (M1/M2/M3) note:** IAG ships as `linux/amd64` only. Docker Desktop runs it via Rosetta emulation automatically. You will see a platform mismatch warning — this is expected and harmless.

### Check your buildx version

```bash
docker buildx version
# Requires: github.com/docker/buildx v0.17.0 or later
```

If your version is older, update Docker Desktop or install the latest buildx binary:

```bash
BUILDX_VERSION=$(curl -s https://api.github.com/repos/docker/buildx/releases/latest \
  | grep '"tag_name"' | cut -d'"' -f4)

# Apple Silicon (arm64):
curl -Lo ~/.docker/cli-plugins/docker-buildx \
  "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.darwin-arm64"

# Intel Mac (amd64):
# curl -Lo ~/.docker/cli-plugins/docker-buildx \
#   "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.darwin-amd64"

chmod +x ~/.docker/cli-plugins/docker-buildx
docker buildx version
```

---

## Quick Start

```bash
# 1. Clone the repo
git clone <repo-url>
cd iag

# 2. Start the full stack (first run pulls ~2 GB for Jupyter)
docker compose up --build -d

# 3. Wait for all services to be healthy (~60 s on first run)
docker compose ps

# 4. Open in your browser
open http://localhost:9080/jupyter/   # JupyterLab via IAG
open http://localhost:9080/           # WebSocket Demo via IAG
open http://localhost:8080/           # WebSocket Demo direct (bypasses IAG)
```

### Stop / clean up

```bash
# Stop containers (preserves volumes)
docker compose down

# Stop and remove volumes (clears IAG trace logs and statsd logs)
docker compose down -v
```

---

## Endpoints

### Via IAG (port 9080)

| URL | Description |
|---|---|
| `http://localhost:9080/` | WebSocket demo UI |
| `ws://localhost:9080/ws` | WebSocket echo endpoint |
| `http://localhost:9080/jupyter/` | JupyterLab (redirects to `/jupyter/lab`) |
| `ws://localhost:9080/jupyter/api/kernels/{id}/channels` | Jupyter kernel WebSocket |

### Direct (bypass IAG)

| URL | Description |
|---|---|
| `http://localhost:8080/` | WebSocket demo UI — direct nginx |

---

## Verifying WebSocket Connectivity

### Echo server (curl)

```bash
curl -i \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  http://localhost:9080/ws
# Expect: HTTP/1.1 101 Switching Protocols
```

### Jupyter kernel (Python test script)

```bash
# Install the only dependency
pip install websockets

# Run the test
python3 tests/test_jupyter_ws.py
```

Expected output:
```
IAG → Jupyter WebSocket Test
  Base URL : http://localhost:9080/jupyter
  WS Base  : ws://localhost:9080/jupyter

1. Checking Jupyter API via IAG...
   ✓ Available kernels: ['python3']
2. Getting kernel...
   [reuse]  kernel <uuid>
3. Opening WebSocket: ws://localhost:9080/jupyter/api/kernels/<uuid>/channels
   ✓ execute_reply: ok
   ✓ STDOUT:
     Python 3.13.x on Linux
     WebSocket kernel execution via IAG: OK

All checks passed. IAG → Jupyter WebSocket pipeline is working.
```

---

## Project Structure

```
iag/
├── docker-compose.yaml         # Orchestrates all 5 services
│
├── iag/
│   └── config/
│       └── iag.yaml            # IAG configuration (junctions, tracing, stats)
│
├── nginx/
│   ├── nginx.conf              # Reverse proxy + WebSocket upgrade for /ws
│   └── html/
│       └── index.html          # WebSocket demo UI
│
├── ws-backend/
│   ├── Dockerfile
│   ├── requirements.txt        # websockets==14.1
│   └── server.py               # Python asyncio WebSocket echo server
│
├── statsd/
│   ├── Dockerfile
│   └── server.py               # UDP listener → /var/log/statsd/statsd.log
│
└── tests/
    └── test_jupyter_ws.py      # End-to-end WebSocket kernel test
```

---

## IAG Configuration Reference (`iag/config/iag.yaml`)

### Server

```yaml
server:
  protocols: [http]       # Plain HTTP on port 8080; no SSL
  worker_threads: 300     # General HTTP thread pool
```

### WebSocket threads

The `server.websockets` YAML keys are not mapped in IAG 25.12, so the thread
pool is set directly via raw webseald.conf injection:

```yaml
advanced:
  configuration:
    - stanza: websocket
      entry: max-worker-threads
      operation: set
      value: "50"
    - stanza: websocket
      entry: idle-worker-threads
      operation: set
      value: "25"
```

Without this, all WebSocket upgrade attempts fail with `DPWIV1067W` (0 threads allocated).

### Resource servers (junctions)

```yaml
resource_servers:
  - path: /jupyter          # Must appear BEFORE / — matched first
    connection_type: tcp    # Plain HTTP to backend
    transparent_path: true  # Preserves /jupyter/ prefix → matches Jupyter's base_url
    servers:
      - host: jupyter
        port: 8888

  - path: /                 # Catch-all → nginx
    connection_type: tcp
    transparent_path: false
    servers:
      - host: nginx
        port: 80
```

`transparent_path: true` keeps the full path (e.g. `/jupyter/api/kernels/...`)
when forwarding, which is required for Jupyter's base_url routing to work correctly.

### Access policy

```yaml
policies:
  access:
    - name: allow-all
      paths:
        - path: /*
          match_type: wildcard
      rule: "anyuser entitledto anyresource"
```

This allows unauthenticated access to everything — suitable for local testing.
To enable authentication, replace `anyuser` with `anyauth` and configure an
`identity.oidc` block pointing to your OIDC provider.

### Tracing

```yaml
logging:
  tracing:
    - file_name: /var/iag/logs/trace.log
      component: pdweb.debug
      level: 9
    - file_name: /var/iag/logs/trace.log
      component: pdweb.websocket
      level: 9
```

Trace output is written to the `iag-logs` Docker volume. To read it:

```bash
docker exec iag-iag-1 tail -f /var/iag/logs/trace.log
```

### Statistics (statsd)

```yaml
logging:
  statistics:
    server: statsd      # Docker Compose service name
    port: 8125
    frequency: 10       # Flush interval in seconds
    components:
      - iag.websocket.requests
      - iag.websocket.rejected
      - iag.websocket.timeouts
      - iag.websocket.active
      - pdweb.http
```

The `statsd` service is a lightweight Python UDP listener that writes received
metrics to `/var/log/statsd/statsd.log` (in the `statsd-logs` Docker volume).

To tail the statsd log:

```bash
docker exec iag-statsd-1 tail -f /var/log/statsd/statsd.log
```

> **macOS / Apple Silicon note:** IAG runs under Rosetta emulation and
> webseald's internal DNS resolver may not resolve Docker service names.
> If no metrics appear in the statsd log after several minutes of WebSocket
> activity, replace `server: statsd` with the container's actual IP:
>
> ```bash
> docker inspect iag-statsd-1 | grep '"IPAddress"'
> # Then set: server: 172.18.0.x
> ```

---

## Jupyter Configuration

JupyterLab is started with:

| Setting | Value | Reason |
|---|---|---|
| `ServerApp.token` | `''` | Disable token auth for local testing |
| `ServerApp.password` | `''` | Disable password auth |
| `ServerApp.base_url` | `/jupyter/` | Matches the IAG junction path |
| `ServerApp.allow_origin` | `'*'` | Allow browser connections through IAG |
| `ServerApp.ip` | `0.0.0.0` | Listen on all interfaces inside the container |

> **Security note:** Token auth is disabled for convenience in this demo.
> Never deploy this configuration in a shared or production environment.
> Re-enable with `--ServerApp.token=<token>` and configure IAG's
> identity provider for proper authentication.

---

## Useful Commands

```bash
# View logs for all services
docker compose logs -f

# View IAG access log only
docker logs -f iag-iag-1

# Check IAG health
docker inspect --format='{{.State.Health.Status}}' iag-iag-1

# List running Jupyter kernels via IAG
curl -s http://localhost:9080/jupyter/api/kernels | python3 -m json.tool

# Restart just IAG (picks up iag/config/iag.yaml changes)
docker compose restart iag

# Rebuild and restart everything
docker compose up --build -d
```

---

## Troubleshooting

### `compose build requires buildx 0.17.0 or later`
Update Docker Desktop or install the latest buildx binary (see Prerequisites).

### `DPWIV1067W — No threads are available to proxy the WebSocket connection`
The WebSocket thread pool is 0. This means the `advanced.configuration` block
in `iag.yaml` was not applied. Verify the config is mounted and restart IAG:
```bash
docker compose restart iag
docker exec iag-iag-1 grep max-worker-threads /var/pdweb/default/etc/webseald-default.conf
# Should show: max-worker-threads = 50
```

### Jupyter returns 404 via IAG but works on port 8888 directly
IAG needs to be restarted after changing `iag.yaml` (config is read at startup):
```bash
docker compose restart iag
```

Also confirm the `/jupyter` resource server appears before `/` in `iag.yaml`.

### Platform mismatch warning on Apple Silicon
```
The requested image's platform (linux/amd64) does not match the detected host platform (linux/arm64/v8)
```
This warning is expected. IAG runs under Rosetta 2 emulation and works correctly.
All other images (`nginx`, `jupyter`, `ws-backend`, `statsd`) are native ARM64.

---

## Next Steps

- **Add authentication:** Configure `identity.oidc` in `iag.yaml` to protect
  Jupyter and the WebSocket demo behind IBM Security Verify or any OIDC provider.
- **Enable SSL:** Add `https` to `server.protocols` and provide a certificate
  under `server.ssl.front_end` for production deployments.
- **Persistent notebooks:** Mount a host volume into the Jupyter container for
  notebook persistence across restarts.
- **Production statsd:** Replace the custom statsd listener with a full
  [Graphite + statsd](https://graphiteapp.org/) stack or route metrics to
  Prometheus via the [statsd_exporter](https://github.com/prometheus/statsd_exporter).

---

## References

- [IBM Application Gateway 25.12 Documentation](https://www.ibm.com/docs/en/iag/25.12.0)
- [IAG YAML Schema Reference](https://ibm-security.github.io/ibm-application-gateway-resources/schema/)
- [IAG Container Registry](https://docs.verify.ibm.com/gateway/docs/containers)
- [Jupyter Docker Stacks](https://jupyter-docker-stacks.readthedocs.io/)
