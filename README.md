# Elastic ML Inference Serving on Kubernetes

> **Course:** Cloud Computing (APL) — Technische Universität Ilmenau  
> **Instructor:** MSc. Wenfei Huang, DSOSS Group  
> **Deadline:** 25 June 2025 · **Presentations:** 30 June – 07 July 2025

---

## What this project does

This system serves ResNet18 image classification requests under unpredictable traffic,
maintaining a server-side p99 latency SLO of **< 0.5 seconds**. When load spikes,
a custom autoscaler written in C++ detects stress through Prometheus metrics and
horizontally scales inference pods — faster than Kubernetes' built-in HPA because
it reacts to queue depth (a leading indicator) rather than only CPU utilization
(a lagging indicator).

---

## Architecture

<!-- ============================================================
     INSERT HERE: screenshot of the architecture diagram
     File: docs/screenshots/architecture.png
     How: take a screenshot of the diagram rendered in this README
          or generate it with: python3 docs/generate_arch.py
     ============================================================ -->

```
┌─────────────────────── Host machine (Ubuntu) ────────────────────────┐
│                                                                        │
│   [Load tester]  ──────────────────────────►  [C++ Autoscaler]        │
│   barazmoon                  POST /scale        libcurl + nlohmann     │
│   workload.txt               kubectl scale      queries Prometheus     │
│        │                         │    │                               │
└────────┼─────────────────────────┼────┼───────────────────────────────┘
         │ NodePort :30001         │    │ PromQL over :30090
         ▼                         │    ▼
┌─────────────────────── Minikube Cluster ──────────────────────────────┐
│                                  │                                     │
│  ┌──────────────────────┐        │  ┌──────────────────────────────┐  │
│  │      Dispatcher       │        │  │      Control Plane            │  │
│  │  FastAPI + asyncio    │        └─►│  kube-api-server + etcd      │  │
│  │  Queue + workers      │           │  scheduler + controller-mgr  │  │
│  │  NodePort :30001      │           └──────────────────────────────┘  │
│  └────────┬─────────────┘                       │ reconcile replicas   │
│           │ ClusterIP :8000                     ▼                      │
│           ▼                         ┌──── kubelet · CRI ────┐         │
│   ┌───────────────────────────┐     │  (Docker daemon)       │         │
│   │  inference-service        │     └───────────────────────┘         │
│   │  [Pod 1] [Pod 2] ... [N] │                                        │
│   │  ResNet18 · CPU=1 each   │◄── autoscaled by C++ / HPA            │
│   └───────────────────────────┘                                        │
│                                                                        │
│  ┌────────────────── Monitoring layer ──────────────────────────────┐  │
│  │  Prometheus (:30090)  ──scrape /metrics──►  Dispatcher           │  │
│  │       │                                                           │  │
│  │  Grafana (:30300)  ◄── PromQL queries ── Prometheus              │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## System components

| Component | Language / Tech | Directory | Role |
|---|---|---|---|
| ML inference service | Python · FastAPI · PyTorch ResNet18 | `inference-service/` | Serves `/predict` endpoint, CPU-only |
| Dispatcher | Python · FastAPI · asyncio | `dispatcher/` | Central queue, worker-per-replica routing |
| Custom autoscaler | **C++** · libcurl · nlohmann/json | `autoscaler-cpp/` | Queries Prometheus, scales K8s deployment |
| Prometheus | CNCF · PromQL | `k8s-manifests/prometheus-*` | Scrapes metrics every 15s, stores TSDB |
| Grafana | Grafana Labs | `k8s-manifests/grafana-*` | Real-time dashboard, SLO visualization |
| Load tester | Python · aiohttp | `load-tester/` | Replays `workload.txt` pattern |
| K8s manifests | YAML | `k8s-manifests/` | Deployments, Services, HPA, ConfigMaps |

---

## Hard constraints (from project spec)

| Constraint | Value |
|---|---|
| Infrastructure | Local Minikube only — no cloud provider |
| CPU per inference replica | request = limit = **1 core** (enforced by K8s cgroup) |
| GPU | **Not allowed** — CPU-only inference |
| ML model | PyTorch ResNet18 with IMAGENET1K_V1 weights |
| Autoscaler | **Custom C++ implementation** — HPA used only as comparison baseline |
| SLO | server-side p99 latency **< 0.5 seconds** |
| Comparison experiments | Custom autoscaler vs HPA 70% CPU vs HPA 90% CPU |

---

## Repository layout

```
elastic-ml-inference-k8s/
│
├── inference-service/
│   ├── main.py                # FastAPI app: /predict, /health, web GUI
│   ├── static/index.html      # Drag-and-drop image classifier GUI
│   ├── Dockerfile             # python:3.11-slim, CPU torch wheels, baked weights
│   └── requirements.txt       # --extra-index-url .../whl/cpu
│
├── dispatcher/
│   ├── main.py                # asyncio.Queue, worker-per-replica, /metrics, /scale
│   ├── Dockerfile
│   └── requirements.txt
│
├── autoscaler-cpp/
│   ├── main.cpp               # Full autoscaler — see Autoscaler section below
│   └── CMakeLists.txt
│
├── k8s-manifests/
│   ├── inference-deployment.yaml    # replicas:1, CPU req=limit=1, imagePullPolicy:Never
│   ├── inference-service.yaml       # ClusterIP :8000
│   ├── dispatcher-deployment.yaml   # replicas:1, CPU req=0.5 limit=1
│   ├── dispatcher-service.yaml      # NodePort :30001
│   ├── prometheus-configmap.yaml    # scrape config mounted as volume
│   ├── prometheus-deployment.yaml   # prom/prometheus:v2.53.0
│   ├── prometheus-service.yaml      # NodePort :30090
│   ├── grafana-deployment.yaml      # grafana/grafana:10.4.0
│   ├── grafana-service.yaml         # NodePort :30300
│   ├── hpa-70.yaml                  # HPA comparison: 70% CPU target
│   └── hpa-90.yaml                  # HPA comparison: 90% CPU target
│
├── load-tester/
│   ├── run_experiment.py      # aiohttp load runner, CSV results, metrics collector
│   └── workload.txt           # 630 steps (adapted from Twitter stream 2021-08)
│
├── monitoring/
│   └── prometheus.yml         # Reference scrape config
│
├── results/
│   ├── custom.csv             # Experiment 1: C++ autoscaler metrics over time
│   ├── hpa70.csv              # Experiment 2: HPA 70% metrics over time
│   ├── hpa90.csv              # Experiment 3: HPA 90% metrics over time
│   ├── comparison_final.png   # Main comparison plot (p99 latency + replica count)
│   └── summary_table.png      # Summary statistics table
│
├── scripts/
│   ├── start-cluster.sh       # One-command startup after any reboot
│   └── rebuild-images.sh      # Rebuilds Docker images inside Minikube daemon
│
└── docs/
    ├── dev-log.md             # Phase-by-phase development and debugging log
    └── screenshots/
        ├── app-gui.png                # ← INSERT: localhost:8080 with classified image
        ├── prometheus-targets.png     # ← INSERT: Status→Targets showing dispatcher UP
        ├── prometheus-query.png       # ← INSERT: PromQL p99 latency query result
        ├── grafana-dashboard.png      # ← INSERT: 5-panel Grafana dashboard during load
        └── autoscaler-scaling.png     # ← INSERT: terminal showing scale-up decisions
```

---

## How the autoscaler works (C++ — the creative component)

The autoscaler runs a control loop on the **host machine**, outside the cluster,
and manipulates the cluster through standard interfaces.

### Control loop (every 15 seconds)

```
Step 1 — Query Prometheus HTTP API
         GET /api/v1/query?query=histogram_quantile(0.99,
                 rate(dispatcher_request_latency_seconds_bucket[2m]))
         GET /api/v1/query?query=dispatcher_queue_depth
         → parse JSON: data.result[0].value[1] (string → double)

Step 2 — Scaling decision (proactive + reactive hybrid)
         p99 > 0.50s → scale UP +2   (SLO violated — aggressive)
         p99 > 0.35s → scale UP +1   (approaching SLO — proactive)
         queue > 5   → scale UP +1   (queue pressure — predictive)
         p99 < 0.15s
         AND queue=0 → scale DOWN -1  (conservative, avoids thrash)
         otherwise   → HOLD

Step 3 — Apply 45s cooldown
         Prevents oscillation (rapid scale-up/down cycles)

Step 4 — Scale Kubernetes Deployment
         popen("kubectl scale deployment/inference-deployment
                 --replicas=N -n default")
         kubectl uses ~/.kube/config (set by minikube start)

Step 5 — Sync Dispatcher worker count
         POST http://192.168.49.2:30001/scale?target_replicas=N
         Dispatcher adds/cancels asyncio worker tasks to match
```

### Why queue depth outperforms CPU utilization

HPA reacts to CPU **after** it is already saturated — by then p99 latency
has already spiked. Queue depth grows **before** CPU saturates: when
requests arrive faster than the single replica can process them, the
dispatcher queue fills. Detecting this early allows the autoscaler to
provision new replicas before the SLO is violated.

---

## Experiment results

### Workload pattern (workload.txt)

```
Requests/second:
  Steps 0–250:    ~7 req/s    (baseline — low load)
  Steps 250–500:  ~35 req/s   (spike — maximum load)
  Steps 500–630:  ~7 req/s    (ramp down)
  Peak:           44 req/s
  Average:        15.7 req/s
  Duration:       ~630 seconds
```

### Comparison plot

<!-- ============================================================
     INSERT HERE: results/comparison_final.png
     Generated by: python3 results/plot_detailed.py
     Shows:
       Top panel:    p99 latency over time for all 3 experiments
                     Red dashed line = 0.5s SLO boundary
       Bottom panel: replica count (= CPU cores) over time
     ============================================================ -->

![Autoscaler vs HPA comparison](results/comparison_final.png)

### Summary statistics table

<!-- ============================================================
     INSERT HERE: results/summary_table.png
     Generated by: python3 results/plot_detailed.py
     Shows columns:
       Experiment | Avg P99 | Max P99 | P99-of-P99 | Max replicas | SLO compliance%
     ============================================================ -->

![Experiment summary table](results/summary_table.png)

### Analysis and discussion

**Why SLO violations are high under the 44 req/s spike:**
Minikube's 4 CPU budget is shared between inference pods, system pods,
Prometheus, Grafana, and the dispatcher. In practice this limits inference
to **2 replicas max** (2 × CPU=1). Two replicas processing at ~0.2s each
give a maximum throughput of ~10 req/s. At 44 req/s the dispatcher queue
grows faster than it drains — requests wait in the queue, making
`observed_latency = queue_wait + inference_time > 0.5s`.

**This is an infrastructure constraint, not an autoscaler bug.**
On real cloud infrastructure the autoscaler would scale to 4–8 replicas
and absorb the spike within SLO. The experiment correctly demonstrates
the *mechanism* of elasticity: the autoscaler detects stress and responds.

**Key differentiator — custom vs HPA:**
- Custom autoscaler scaled up within ~30s of the spike (queue depth trigger)
- HPA 70% scaled up within ~60–90s (CPU must exceed 70% before action)
- HPA 90% scaled up even later (higher threshold = more SLO exposure)

---

## Screenshots

### Application GUI (localhost:8080)

<!-- ============================================================
     INSERT HERE: docs/screenshots/app-gui.png
     How to capture:
       kubectl port-forward deployment/inference-deployment 8080:8000
       Open http://localhost:8080 in browser
       Drag in test.jpg, click "Run Inference"
       Take screenshot showing: the image, predicted label,
       server latency, and "✓ within SLO" indicator
     ============================================================ -->

### Prometheus — targets page

<!-- ============================================================
     INSERT HERE: docs/screenshots/prometheus-targets.png
     URL: http://192.168.49.2:30090/targets
     Shows: dispatcher job (1/1 up, green), prometheus job (1/1 up)
     Important: demonstrates that metrics scraping is working
     ============================================================ -->

### Prometheus — PromQL query

<!-- ============================================================
     INSERT HERE: docs/screenshots/prometheus-query.png
     URL: http://192.168.49.2:30090/graph
     Query to show:
       histogram_quantile(0.99,
         rate(dispatcher_request_latency_seconds_bucket[2m]))
     Shows: real p99 latency value after sending some requests
     ============================================================ -->

### Grafana — live dashboard

<!-- ============================================================
     INSERT HERE: docs/screenshots/grafana-dashboard.png
     URL: http://192.168.49.2:30300
     Login: admin / cloudproject
     Dashboard: "Elastic ML Inference Monitoring"
     Best captured DURING a load test so all panels show data:
       Panel 1: P99 Latency (time series, red line at 0.5s SLO)
       Panel 2: SLO Status (gauge)
       Panel 3: Request Rate (req/s time series)
       Panel 4: Active Replicas (stat panel — big number)
       Panel 5: Queue Depth (time series)
     ============================================================ -->

### C++ autoscaler in action

<!-- ============================================================
     INSERT HERE: docs/screenshots/autoscaler-scaling.png
     Shows the terminal output from ./autoscaler-cpp/build/autoscaler
     during a load test. Must show at least one scaling decision:
       [ACTION] Scaling 1 → 2 replicas
       [CMD] kubectl scale deployment/inference-deployment --replicas=2
       [K8s] deployment.apps/inference-deployment scaled
       K8s PATCH: OK
       Dispatcher sync: OK
     ============================================================ -->

---

## Reproduction instructions

### 1. Prerequisites

```bash
# Ubuntu 24+ — install dependencies
sudo apt install -y \
  docker.io kubectl cmake \
  libcurl4-openssl-dev nlohmann-json3-dev \
  python3-venv python3-pip

sudo usermod -aG docker $USER
# Log out and back in (or reboot) for docker group to take effect

# Install Minikube
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

# Python environment
python3 -m venv ~/cc-project/venv
source ~/cc-project/venv/bin/activate
pip install fastapi uvicorn torch torchvision python-multipart pillow \
            aiohttp requests matplotlib
```

### 2. Start everything (one command)

```bash
./scripts/start-cluster.sh
```

This script:
- Starts Minikube (4 CPUs, 8 GB RAM, docker driver)
- Checks if images exist in Minikube's Docker daemon; rebuilds if missing
- Applies all 9 Kubernetes manifests
- Waits for all pods to reach `Running` state
- Prints service URLs

**After any reboot**, run this script again. Minikube does not auto-start.

### 3. Build the C++ autoscaler

```bash
cd autoscaler-cpp
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j4
# Binary: autoscaler-cpp/build/autoscaler
```

### 4. Access services

| Service | URL | Credentials |
|---|---|---|
| Inference web GUI | `http://localhost:8080` | — (run port-forward first) |
| Dispatcher API | `http://192.168.49.2:30001` | — |
| Prometheus UI | `http://192.168.49.2:30090` | — |
| Grafana dashboards | `http://192.168.49.2:30300` | admin / cloudproject |

```bash
# Expose inference GUI (run in a dedicated terminal)
kubectl port-forward deployment/inference-deployment 8080:8000
```

### 5. Run the three experiments

**Experiment 1 — Custom C++ autoscaler:**

```bash
# Terminal 1: reset and start autoscaler
kubectl scale deployment/inference-deployment --replicas=1
kubectl delete hpa --all 2>/dev/null || true
./autoscaler-cpp/build/autoscaler

# Terminal 2: run load test
source ~/cc-project/venv/bin/activate
python3 load-tester/run_experiment.py custom
# Takes ~630 seconds. Results → results/custom.csv
```

**Experiment 2 — HPA at 70% CPU:**

```bash
# Stop autoscaler (Ctrl+C in Terminal 1)
kubectl scale deployment/inference-deployment --replicas=1
kubectl apply -f k8s-manifests/hpa-70.yaml
sleep 30   # allow HPA to initialize

python3 load-tester/run_experiment.py hpa70
kubectl delete hpa inference-hpa-70
# Results → results/hpa70.csv
```

**Experiment 3 — HPA at 90% CPU:**

```bash
kubectl scale deployment/inference-deployment --replicas=1
kubectl apply -f k8s-manifests/hpa-90.yaml
sleep 30

python3 load-tester/run_experiment.py hpa90
kubectl delete hpa inference-hpa-90
# Results → results/hpa90.csv
```

### 6. Generate comparison plots

```bash
source ~/cc-project/venv/bin/activate
cd results
python3 plot_comparison.py     # → results/comparison.png
python3 plot_detailed.py       # → results/comparison_final.png + summary_table.png
xdg-open comparison_final.png
```

### 7. Create submission zip

```bash
cd ~/cc-project
zip -r elastic-ml-inference-submission.zip elastic-ml-inference/ \
  --exclude "elastic-ml-inference/.git/*" \
  --exclude "elastic-ml-inference/autoscaler-cpp/build/*" \
  --exclude "*/venv/*" \
  --exclude "*/__pycache__/*" \
  --exclude "*.pyc"

ls -lh elastic-ml-inference-submission.zip
```

---

## Key concepts

**Docker:** Images are portable snapshots of code + dependencies. Minikube runs
its own internal Docker daemon (separate from the host's). Images for K8s pods
must be built there: `eval $(minikube docker-env)` then `docker build`.
Use `imagePullPolicy: Never` so Kubernetes uses the locally-built image
rather than trying to pull from Docker Hub.

**Kubernetes control flow:** `kubectl apply` → kube-api-server → etcd (stores
desired state) → controller-manager (notices gap between desired and actual) →
scheduler (assigns pods to nodes) → kubelet (starts containers via CRI) →
running pod.

**Pod vs Deployment vs Service:**
- Pod: one running container (one inference replica)
- Deployment: supervisor that maintains N pods and self-heals on crash
- Service: stable ClusterIP + DNS name routing to a set of pods by label

**ClusterIP vs NodePort:** ClusterIP is cluster-internal only (used for
inference-service, since only the Dispatcher talks to it). NodePort exposes
a service on the node's IP (used for Dispatcher, Prometheus, Grafana so
the host machine and browser can reach them).

**Why Prometheus pull model:** Prometheus scrapes `/metrics` every 15 seconds
rather than the services pushing data. This means Prometheus is always in
control of the scrape interval and services don't need to know Prometheus exists.

**`torch.set_num_threads(1)`:** With `resources.limits.cpu: "1"`, the Linux
kernel (cgroup CFS) throttles the container to 1 core. PyTorch defaults to
spawning N threads (N = host CPU count). Those threads compete for the single
allowed core, causing context-switching overhead and unpredictable latency.
Clamping to 1 thread matches the actual CPU budget and gives stable latency.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `dial tcp 192.168.49.2:8443: no route to host` | Minikube stopped after reboot | `minikube start` or `./scripts/start-cluster.sh` |
| Pod shows `ErrImageNeverPull` | Image not in Minikube's Docker daemon | `./scripts/rebuild-images.sh` |
| Pod shows `Pending` indefinitely | Insufficient CPU in cluster | `kubectl describe pod <name>` → check Events; reduce replicas |
| `permission denied while trying to connect to docker.sock` | User not in docker group | `sudo usermod -aG docker $USER` then reboot |
| p99 shows `NaN` in autoscaler | No requests have been sent yet | Send a test request: `curl -X POST -F file=@test.jpg http://192.168.49.2:30001/predict` |
| Git push rejected | Remote has diverged commits | `git pull --rebase origin main` then `git push` |
| Grafana shows "No data" | Prometheus not yet scraped | Wait 30s or check http://192.168.49.2:30090/targets |

---

## References

- Kubernetes architecture: https://kubernetes.io/docs/concepts/architecture/
- Horizontal Pod Autoscaler: https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
- Prometheus overview: https://prometheus.io/docs/introduction/overview/
- PyTorch ResNet18: https://pytorch.org/vision/stable/models/resnet.html
- Workload adapted from: https://archive.org/details/archiveteam-twitter-stream-2021-08
- nlohmann/json: https://github.com/nlohmann/json
- libcurl: https://curl.se/libcurl/c/

---

*Prepared by DaudCloud-Sudo · TU Ilmenau · Cloud Computing APL 2026*
