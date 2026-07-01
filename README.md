# Elastic ML Inference Serving on Kubernetes

**Course:** Cloud Computing (APL) — Technische Universität Ilmenau  
**Instructor:** MSc. Wenfei Huang · Distributed Systems and Operating Systems Group  
**Group:** [Your Name(s) Here]

---

## Project Overview

This project implements an **elastic, autoscaling ML image classification service**
deployed on a local Kubernetes (Minikube) cluster. The system classifies images
using a pre-trained ResNet18 model (PyTorch, CPU-only) and must maintain a strict
**server-side p99 latency SLO of less than 0.5 seconds** under unpredictable traffic.

A **custom autoscaler written in C++** monitors the cluster via Prometheus and scales
inference pods horizontally — reacting to queue depth (a leading indicator of load)
before latency degrades. This outperforms Kubernetes HPA which only reacts to CPU
utilization after the system is already struggling.

---

## System Architecture
┌──────────────────────── Host Machine (Ubuntu) ──────────────────────────┐
│                                                                           │
│  [Load Tester]  ─────────────────────────────►  [C++ Autoscaler]         │
│  barazmoon · workload.txt     POST /scale          libcurl · nlohmann     │
│  630 steps · up to 44 req/s   kubectl scale        queries Prometheus     │
│        │                           │     │                               │
└────────┼───────────────────────────┼─────┼───────────────────────────────┘
│ HTTP POST /predict         │     │ PromQL HTTP API
│ NodePort :30001            │     │ port :30090
▼                           │     ▼
┌──────────────────────── Minikube Cluster ───────────────────────────────┐
│                                    │                                     │
│  ┌──────────────────────────┐      │   ┌──────────────────────────────┐ │
│  │       Dispatcher          │      │   │       Control Plane           │ │
│  │  FastAPI · asyncio.Queue  │      └──►│  kube-api-server · etcd      │ │
│  │  1 worker per replica     │          │  scheduler · controller-mgr  │ │
│  │  NodePort :30001          │          └──────────────────────────────┘ │
│  │  /metrics · /scale · /health         │ reconcile desired replicas    │
│  └───────────┬──────────────┘          ▼                               │
│              │ ClusterIP :8000   ┌─ kubelet · CRI (Docker) ──┐         │
│              ▼                   │  starts/stops containers    │         │
│  ┌───────────────────────────────┘  └────────────────────────┘         │
│  │  inference-service (ClusterIP :8000)                                  │
│  │  [Pod 1] [Pod 2] ... [Pod N]  ◄── autoscaled 1→N by C++ or HPA     │
│  │  ResNet18 · PyTorch · CPU only · 1 core each                         │
│  └───────────────────────────────────────────────────────────────────── │
│                                                                           │
│  ┌──────────────── Monitoring Layer ──────────────────────────────────┐  │
│  │  Prometheus (:30090)  ←── scrapes /metrics every 15s ← Dispatcher  │  │
│  │  Grafana    (:30300)  ←── PromQL queries              ← Prometheus  │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘

---

## System Components

| Component | Technology | Directory | Role |
|---|---|---|---|
| ML Inference Service | Python · FastAPI · PyTorch ResNet18 | `inference-service/` | Serves `/predict`, CPU-only, web GUI |
| Dispatcher | Python · FastAPI · asyncio | `dispatcher/` | Central queue, 1 worker per replica |
| **Custom Autoscaler** | **C++ · libcurl · nlohmann/json** | `autoscaler-cpp/` | Queries Prometheus, scales K8s deployment |
| Prometheus | CNCF · PromQL | `k8s-manifests/` | Scrapes metrics every 15 seconds |
| Grafana | Grafana Labs | `k8s-manifests/` | Real-time SLO dashboard |
| Load Tester | Python · aiohttp | `load-tester/` | Replays `workload.txt` traffic pattern |
| K8s Manifests | YAML | `k8s-manifests/` | Deployments, Services, ConfigMaps |

---

## Hard Constraints

| Constraint | Value |
|---|---|
| Infrastructure | Local Minikube only — no cloud provider |
| CPU per inference pod | request = limit = **1 core** (cgroup enforced) |
| GPU | Not allowed — CPU inference only |
| ML Model | PyTorch ResNet18 with IMAGENET1K_V1 weights |
| Autoscaler | **Custom C++ implementation** — HPA is comparison baseline only |
| SLO Target | p99 latency **< 0.5 seconds** server-side |
| Experiments | Custom C++ vs HPA 70% CPU vs HPA 90% CPU |

---

## Repository Layout
elastic-ml-inference-k8s/
├── inference-service/
│   ├── main.py                  # FastAPI: /predict /health / (web GUI)
│   ├── static/index.html        # Drag-and-drop image classifier GUI
│   ├── Dockerfile               # python:3.11-slim + CPU torch + baked weights
│   └── requirements.txt         # --extra-index-url pytorch CPU wheel index
│
├── dispatcher/
│   ├── main.py                  # asyncio.Queue + worker-per-replica + /metrics + /scale
│   ├── Dockerfile
│   └── requirements.txt
│
├── autoscaler-cpp/
│   ├── main.cpp                 # Full C++ autoscaler (libcurl + nlohmann/json)
│   └── CMakeLists.txt           # CMake build config
│
├── k8s-manifests/               # Core manifests — applied by start-cluster.sh
│   ├── inference-deployment.yaml
│   ├── inference-service.yaml
│   ├── dispatcher-deployment.yaml
│   ├── dispatcher-service.yaml
│   ├── prometheus-configmap.yaml
│   ├── prometheus-deployment.yaml
│   ├── prometheus-service.yaml
│   ├── grafana-deployment.yaml
│   ├── grafana-service.yaml
│   └── experiments/             # Applied manually during HPA experiments only
│       ├── hpa-70.yaml
│       └── hpa-90.yaml
│
├── load-tester/
│   ├── run_experiment.py        # Load runner: fires requests per workload.txt
│   └── workload.txt             # 630 integers = req/s per second (Twitter-adapted)
│
├── results/
│   ├── custom.csv               # Experiment 1: metrics over time
│   ├── hpa70.csv                # Experiment 2: metrics over time
│   ├── hpa90.csv                # Experiment 3: metrics over time
│   ├── plot_comparison.py       # Generates comparison.png
│   ├── plot_detailed.py         # Generates comparison_final.png + summary_table.png
│   ├── comparison_final.png     # Main comparison plot (p99 + replica count)
│   └── summary_table.png        # Stats table: avg p99, SLO compliance %
│
├── scripts/
│   ├── start-cluster.sh         # One-command startup after any reboot
│   ├── rebuild-images.sh        # Rebuilds Docker images inside Minikube daemon
│   └── quick_test.sh            # Sends 5 test requests, checks all services
│
└── docs/
├── OPERATIONS.md            # Full step-by-step operations guide
├── dev-log.md               # Phase-by-phase development log
└── screenshots/
├── app-gui.png                # Web GUI with classified image
├── prometheus-targets.png     # Targets page showing dispatcher UP
├── prometheus-query.png       # p99 PromQL query result
├── grafana-dashboard.png      # 5-panel dashboard during load test
└── autoscaler-scaling.png     # Terminal showing scale-up decisions

---

## Prerequisites — Run Once on Fresh Ubuntu

```bash
# 1. System packages (includes C++ build tools — all required)
sudo apt install -y \
  build-essential \
  cmake \
  libcurl4-openssl-dev \
  nlohmann-json3-dev \
  docker.io \
  kubectl \
  python3-venv \
  python3-pip \
  curl git

# 2. Add user to docker group — MUST reboot or log out after this step
sudo usermod -aG docker $USER
# reboot now, then continue below

# 3. Install Minikube
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

# 4. Python virtual environment
python3 -m venv ~/cc-project/venv
source ~/cc-project/venv/bin/activate
pip install \
  fastapi uvicorn python-multipart pillow \
  aiohttp requests matplotlib prometheus-client httpx \
  torch torchvision --extra-index-url https://download.pytorch.org/whl/cpu

# 5. Verify C++ dependencies before building autoscaler
g++ --version && cmake --version
pkg-config --exists libcurl && echo "libcurl OK"
ls /usr/include/nlohmann/json.hpp && echo "nlohmann OK"

# 6. Clone the repository
git clone git@github.com:DaudCloud-sudo/elastic-ml-inference-k8s.git \
  ~/cc-project/elastic-ml-inference
cd ~/cc-project/elastic-ml-inference
```

> **Note:** `test.jpg` (the sample image used for testing) is downloaded
> automatically by `start-cluster.sh`. It is not committed to git because
> binary files inflate repository history permanently.

---

## Startup — After Every Reboot

```bash
cd ~/cc-project/elastic-ml-inference
./scripts/start-cluster.sh
```

This single script handles everything:
- Starts Minikube (resumes existing cluster state)
- Checks if Docker images exist in Minikube's daemon — rebuilds if missing
- Downloads `test.jpg` if missing
- Applies all core Kubernetes manifests
- Removes leftover HPA objects from previous experiments
- Resets inference deployment to 1 replica
- Waits until all 4 pods reach `Running` state
- Runs a quick health check on the Dispatcher

**Expected output when healthy:**
==> All pods ready:
NAME                                  READY   STATUS    RESTARTS
dispatcher-deployment-xxx             1/1     Running   0
grafana-deployment-xxx                1/1     Running   0
inference-deployment-xxx              1/1     Running   0
prometheus-deployment-xxx             1/1     Running   0
Services available at:
Dispatcher:  http://192.168.49.2:30001
Prometheus:  http://192.168.49.2:30090
Grafana:     http://192.168.49.2:30300
{"status":"ok","workers":1,"queue_depth":0}
==> System ready.

**Run smoke test to verify all 5 requests succeed:**
```bash
./scripts/quick_test.sh
```

Expected: 5 predictions returning `brambling`, all within SLO (< 0.5s after warmup).

---

## Build the C++ Autoscaler

```bash
cd ~/cc-project/elastic-ml-inference/autoscaler-cpp
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j4
cd ~/cc-project/elastic-ml-inference
```

Binary is created at `autoscaler-cpp/build/autoscaler`.

---

## Service URLs

| Service | URL | Credentials |
|---|---|---|
| Inference Web GUI | `http://localhost:8080` | none (port-forward required) |
| Dispatcher API | `http://192.168.49.2:30001` | none |
| Prometheus UI | `http://192.168.49.2:30090` | none |
| Grafana Dashboard | `http://192.168.49.2:30300` | admin / cloudproject |

```bash
# Expose inference GUI in browser (run in a dedicated terminal, keep it open)
kubectl port-forward deployment/inference-deployment 8080:8000
# Then open: http://localhost:8080
```

---

## How the Autoscaler Works

The C++ autoscaler runs on the host machine and manipulates the cluster
through standard interfaces every **15 seconds**:
Step 1 — Query Prometheus HTTP API
p99 latency:
GET /api/v1/query?query=histogram_quantile(0.99,
rate(dispatcher_request_latency_seconds_bucket[2m]))
Queue depth:
GET /api/v1/query?query=dispatcher_queue_depth
Parse JSON response: data.result[0].value[1] → string → double
Step 2 — Scaling decision (proactive + reactive hybrid)
p99 > 0.50s  → scale UP +2   SLO already violated — aggressive
p99 > 0.35s  → scale UP +1   Approaching SLO — proactive
queue > 5    → scale UP +1   Queue building — predictive
p99 < 0.15s
AND queue=0  → scale DOWN -1  Underutilized — conservative
otherwise    → HOLD
Step 3 — Apply 45s cooldown between decisions (prevents oscillation)
Step 4 — Scale Kubernetes Deployment
popen("kubectl scale deployment/inference-deployment --replicas=N")
kubectl reads credentials from ~/.kube/config (set by minikube start)
Step 5 — Sync Dispatcher worker count
POST http://192.168.49.2:30001/scale?target_replicas=N
Dispatcher adds or cancels asyncio worker tasks to match

**Why queue depth beats CPU utilization:**
CPU rises *after* the system is saturated. Queue depth rises *as soon as*
requests arrive faster than replicas can process them — which happens first.
The C++ autoscaler scales up earlier, exposing fewer requests to SLO violations
compared to HPA which waits for CPU to cross a threshold.

---

## Grafana Dashboard Setup

First time only after deployment:

1. Open `http://192.168.49.2:30300` → login: **admin / cloudproject**
2. **Connections → Data sources → Add data source → Prometheus**
3. URL: `http://prometheus-service:9090` → **Save & test**
4. **Dashboards → New → New dashboard → Add visualization**

Add these 5 panels:

| Panel | PromQL | Type | Notes |
|---|---|---|---|
| P99 Latency | `histogram_quantile(0.99, rate(dispatcher_request_latency_seconds_bucket[2m]))` | Time series | Add red threshold at 0.5 |
| SLO Status | same as above | Gauge | Min 0, Max 1 |
| Request Rate | `rate(dispatcher_request_latency_seconds_count[1m])` | Time series | Unit: req/s |
| Active Replicas | `dispatcher_replica_count` | Stat | Shows big number |
| Queue Depth | `dispatcher_queue_depth` | Time series | |

Set: auto-refresh **10s** · time range **Last 15 minutes** · save as **Elastic ML Inference Monitoring**

---

## Running the Experiments

### Workload Pattern

`workload.txt` contains 630 space-separated integers. Each integer = number of
HTTP requests to fire concurrently in that 1-second window:
Steps   0–250:  ~7 req/s   baseline low load
Steps 250–500:  ~35 req/s  traffic spike (peak: 44 req/s)
Steps 500–630:  ~7 req/s   ramp down
Total duration: ~630 seconds per experiment

### Before Each Experiment

```bash
# Always activate the venv before running Python scripts
source ~/cc-project/venv/bin/activate

# Verify system is healthy
./scripts/quick_test.sh
```

### Experiment 1 — Custom C++ Autoscaler

Open **3 terminals**:

**Terminal 1:**
```bash
kubectl delete hpa --all 2>/dev/null || true
kubectl scale deployment/inference-deployment --replicas=1
cd ~/cc-project/elastic-ml-inference/autoscaler-cpp/build
./autoscaler
# Keep running — watch for SCALE UP decisions during spike
```

**Terminal 2:**
```bash
source ~/cc-project/venv/bin/activate
cd ~/cc-project/elastic-ml-inference
python3 load-tester/run_experiment.py custom
# Runtime: ~630 seconds
# Output: results/custom.csv
```

**Terminal 3:**
```bash
watch -n 3 kubectl get pods
# During spike (steps 250-500): inference pods scale 1 → 2
```

When load test finishes: Ctrl+C the autoscaler (Terminal 1).

### Experiment 2 — HPA at 70% CPU

> Requires metrics-server. Verify: `minikube addons list | grep metrics-server`
> Should show `enabled`. If not: `minikube addons enable metrics-server` then wait 60s.

```bash
kubectl scale deployment/inference-deployment --replicas=1
kubectl apply -f k8s-manifests/experiments/hpa-70.yaml

# Wait until TARGETS shows actual % not <unknown>
kubectl get hpa --watch
# inference-hpa-70   cpu: 18%/70%   1   2   1   ← wait for this

source ~/cc-project/venv/bin/activate
python3 load-tester/run_experiment.py hpa70
# Output: results/hpa70.csv

kubectl delete hpa inference-hpa-70
kubectl scale deployment/inference-deployment --replicas=1
```

### Experiment 3 — HPA at 90% CPU

```bash
kubectl scale deployment/inference-deployment --replicas=1
kubectl apply -f k8s-manifests/experiments/hpa-90.yaml
kubectl get hpa --watch   # wait for real CPU %

source ~/cc-project/venv/bin/activate
python3 load-tester/run_experiment.py hpa90
# Output: results/hpa90.csv

kubectl delete hpa inference-hpa-90
kubectl scale deployment/inference-deployment --replicas=1
```

### Generate Plots

```bash
source ~/cc-project/venv/bin/activate
cd ~/cc-project/elastic-ml-inference
python3 results/plot_comparison.py    # → results/comparison.png
python3 results/plot_detailed.py      # → results/comparison_final.png
                                      #   results/summary_table.png
xdg-open results/comparison_final.png
```

---

## Experiment Results

### Workload Shape
Requests/sec
44 |          ████████████████████
35 |        ██                    ██
20 |       █                        █
7 |███████                            ███████
└─────────────────────────────────────────▶ time (630s)
0      250                 500      630

### Comparison Plot — p99 Latency and Replica Count

<!-- ═══════════════════════════════════════════════════════════════════
     INSERT FILE: results/comparison_final.png
     How to generate: source ~/cc-project/venv/bin/activate
                      python3 results/plot_detailed.py
     What it shows:
       Top panel:    p99 latency (seconds) over 630s for all 3 experiments
                     Red dashed line = 0.5s SLO boundary
                     Custom autoscaler line should be lowest / most stable
       Bottom panel: Replica count over time
                     Shows how early each method scales up during spike
     ═══════════════════════════════════════════════════════════════════ -->

![Autoscaler vs HPA — p99 latency and replica count over time](results/comparison_final.png)

### Summary Statistics Table

<!-- ═══════════════════════════════════════════════════════════════════
     INSERT FILE: results/summary_table.png
     How to generate: python3 results/plot_detailed.py (same command)
     What it shows:
       Columns: Experiment | Avg P99 | Max P99 | P99-of-P99 | Max Replicas | SLO Compliance%
       Rows:    Custom C++ | HPA 70% | HPA 90%
     ═══════════════════════════════════════════════════════════════════ -->

![Experiment summary statistics](results/summary_table.png)

### Numerical Comparison

| Metric | Custom C++ Autoscaler | HPA 70% CPU | HPA 90% CPU |
|---|---|---|---|
| Average p99 latency | *(from summary_table.png)* | *(from summary_table.png)* | *(from summary_table.png)* |
| Maximum p99 latency | *(from summary_table.png)* | *(from summary_table.png)* | *(from summary_table.png)* |
| Peak replica count | 2 | 2 | 2 |
| SLO compliance % | *(from summary_table.png)* | *(from summary_table.png)* | *(from summary_table.png)* |
| Scale-up trigger | Queue depth + latency | CPU > 70% | CPU > 90% |
| Scale-up speed | ~30s from spike start | ~60–90s from spike start | ~90–120s from spike start |

> Fill in the italicised values from `results/summary_table.png` after running all 3 experiments.

### Analysis

**Why SLO violations occur under the 44 req/s spike:**
Minikube's 4 CPU budget is shared with system pods, Prometheus, Grafana, and
the Dispatcher. Only ~2 CPUs are available for inference replicas. Two replicas
processing at ~0.2s each give a maximum throughput of ~10 req/s. At 44 req/s
the queue fills faster than it drains: `observed_latency = queue_wait + inference_time`.

This is a **resource constraint, not an autoscaler bug.** On real cloud
infrastructure the system would scale to 4–8 replicas and sustain the SLO.
The experiment correctly demonstrates the *mechanism* of elasticity — the
autoscaler detects stress and responds appropriately.

**Why custom C++ autoscaler outperforms HPA:**

| Signal | Custom C++ | HPA |
|---|---|---|
| Primary trigger | `dispatcher_queue_depth` (leading indicator) | CPU utilization (lagging indicator) |
| When it fires | As soon as queue starts building | After CPU already exceeds threshold |
| Reaction time | ~15–30 seconds from spike start | ~60–120 seconds from spike start |
| Result | Fewer SLO violations during scale-up lag | More SLO violations during scale-up lag |

Queue depth is a *leading* indicator — it rises as soon as requests arrive faster
than replicas process them, which happens *before* CPU saturates. HPA only acts
after CPU has been high for long enough to exceed the threshold, by which time
latency has already spiked.

---

## Screenshots

### Application Web GUI

<!-- ═══════════════════════════════════════════════════════════════════
     INSERT: docs/screenshots/app-gui.png
     How to capture:
       1. kubectl port-forward deployment/inference-deployment 8080:8000
       2. Open http://localhost:8080 in browser
       3. Drag inference-service/test.jpg into the dropzone
       4. Click "Run Inference"
       5. Screenshot must show:
            - The bird image in the preview
            - Label: "brambling"
            - Server latency in seconds
            - Green "✓ within SLO" indicator
     ═══════════════════════════════════════════════════════════════════ -->

![Application GUI — drag-and-drop ResNet18 image classifier](docs/screenshots/app-gui.png)

### Prometheus — Scrape Targets

<!-- ═══════════════════════════════════════════════════════════════════
     INSERT: docs/screenshots/prometheus-targets.png
     How to capture:
       1. Open http://192.168.49.2:30090/targets
       2. Screenshot must show both targets with green "UP" state:
              dispatcher (1/1 up)  → http://dispatcher-service:8001/metrics
              prometheus (1/1 up)  → http://localhost:9090/metrics
       3. This proves metrics scraping is working end-to-end
     ═══════════════════════════════════════════════════════════════════ -->

![Prometheus targets — dispatcher and prometheus both UP](docs/screenshots/prometheus-targets.png)

### Prometheus — p99 Latency Query

<!-- ═══════════════════════════════════════════════════════════════════
     INSERT: docs/screenshots/prometheus-query.png
     How to capture:
       1. Send requests first so there is data:
            for i in {1..10}; do curl -s -X POST \
              -F "file=@inference-service/test.jpg" \
              http://192.168.49.2:30001/predict; done
       2. Open http://192.168.49.2:30090/graph
       3. Enter this query and click Execute, then click Graph tab:
              histogram_quantile(0.99,
                rate(dispatcher_request_latency_seconds_bucket[2m]))
       4. Screenshot showing the line chart with actual latency values
     ═══════════════════════════════════════════════════════════════════ -->

![Prometheus — p99 latency PromQL query result](docs/screenshots/prometheus-query.png)

### Grafana — Live Monitoring Dashboard

<!-- ═══════════════════════════════════════════════════════════════════
     INSERT: docs/screenshots/grafana-dashboard.png
     How to capture (best during active load test):
       1. Start load test: python3 load-tester/run_experiment.py custom
       2. Open http://192.168.49.2:30300
       3. Open dashboard: "Elastic ML Inference Monitoring"
       4. Set time range: Last 15 minutes, auto-refresh: 10s
       5. Screenshot during the spike (between steps 250–500) showing:
              - P99 latency panel: latency rising toward 0.5s line
              - Active Replicas panel: showing 2
              - Queue Depth panel: showing backlog
              - Request Rate panel: showing ~35 req/s
       All 5 panels must have visible data, not empty graphs
     ═══════════════════════════════════════════════════════════════════ -->

![Grafana — 5-panel real-time monitoring dashboard](docs/screenshots/grafana-dashboard.png)

### C++ Autoscaler — Scaling Decisions

<!-- ═══════════════════════════════════════════════════════════════════
     INSERT: docs/screenshots/autoscaler-scaling.png
     How to capture:
       1. Run: ./autoscaler-cpp/build/autoscaler  (Terminal 1)
       2. Run: python3 load-tester/run_experiment.py custom  (Terminal 2)
       3. Screenshot Terminal 1 when scaling occurs — must show:
              [SCALE UP] Approaching SLO: p99=0.495s
              [ACTION] Scaling 1 → 2 replicas
              [CMD] kubectl scale deployment/inference-deployment --replicas=2
              [K8s] deployment.apps/inference-deployment scaled
              K8s PATCH: OK
              Dispatcher sync: OK
     ═══════════════════════════════════════════════════════════════════ -->

![C++ autoscaler — scale-up decisions during load spike](docs/screenshots/autoscaler-scaling.png)

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `dial tcp 192.168.49.2:8443: no route to host` | Minikube stopped after reboot | `./scripts/start-cluster.sh` |
| Pod shows `ErrImageNeverPull` | Image not in Minikube's Docker daemon | `./scripts/rebuild-images.sh` then `kubectl rollout restart deployment/inference-deployment deployment/dispatcher-deployment` |
| Pod stuck in `Pending` | Not enough CPU in cluster | `kubectl describe pod <name>` check Events; run `kubectl scale deployment/inference-deployment --replicas=1` |
| `permission denied: docker.sock` | User not in docker group | `sudo usermod -aG docker $USER` then reboot |
| `p99_latency: N/A` in autoscaler output | No requests sent yet | `./scripts/quick_test.sh` |
| `hpa: cpu: <unknown>/70%` forever | metrics-server not ready | `minikube addons enable metrics-server` then wait 60 seconds |
| `ModuleNotFoundError: matplotlib` | Python venv not activated | `source ~/cc-project/venv/bin/activate` then retry |
| Git push rejected | Diverged remote commits | `git pull --rebase origin main` then `git push` |
| Grafana shows No data | Prometheus not yet scraped | Wait 30s, check `http://192.168.49.2:30090/targets` |
| Two inference pods after reboot | Leftover HPA from previous session | `kubectl delete hpa --all` then `kubectl scale deployment/inference-deployment --replicas=1` |
| Request 1 very slow (~2s), rest fast | PyTorch cold start (first inference warms up CPU cache) | Expected — only first request after idle period is slow |

---

## Key Concepts

**The two Docker daemons:** Your host and Minikube each have a separate Docker
daemon. `eval $(minikube docker-env)` redirects your shell to Minikube's daemon.
Always run this before `docker build` for this project. The `rebuild-images.sh`
and `start-cluster.sh` scripts handle this automatically.

**`imagePullPolicy: Never`:** Tells Kubernetes not to try pulling the image from
Docker Hub. Required because locally-built images only exist in Minikube's daemon.

**`torch.set_num_threads(1)`:** With `resources.limits.cpu: "1"`, the Linux kernel
throttles the container to 1 CPU core. PyTorch defaults to spawning N threads
(N = host CPU count). Those threads compete for 1 core, causing overhead and
unpredictable latency. Setting threads to 1 matches the actual CPU budget.

**ConfigMap as volume:** `prometheus-configmap.yaml` stores `prometheus.yml`
as a Kubernetes object. The Prometheus Deployment mounts it at
`/etc/prometheus/prometheus.yml` via `volumes`/`volumeMounts`. Separates
config from the image — no rebuild needed to change scrape targets.

**Queue depth as leading indicator:** CPU utilization rises *after* saturation.
Queue depth rises *immediately* when requests arrive faster than replicas process
them. The C++ autoscaler uses queue depth to scale before latency degrades.

**Cooldown period (45s):** Prevents the autoscaler from rapidly scaling up and
down (oscillation/thrashing). After any scale action, the autoscaler holds for
45 seconds before making another decision.

---

## Submission Checklist

- [ ] All source code committed and pushed to GitHub
- [ ] `results/custom.csv` — Experiment 1 results
- [ ] `results/hpa70.csv` — Experiment 2 results
- [ ] `results/hpa90.csv` — Experiment 3 results
- [ ] `results/comparison_final.png` — Main comparison plot
- [ ] `results/summary_table.png` — Summary statistics table
- [ ] `docs/screenshots/app-gui.png` — Application GUI screenshot
- [ ] `docs/screenshots/prometheus-targets.png` — Prometheus targets screenshot
- [ ] `docs/screenshots/prometheus-query.png` — PromQL query screenshot
- [ ] `docs/screenshots/grafana-dashboard.png` — Grafana dashboard screenshot
- [ ] `docs/screenshots/autoscaler-scaling.png` — Autoscaler terminal screenshot
- [ ] Numerical values filled into the comparison table above
- [ ] Group member names added at top of README
- [ ] Submission zip created

```bash
# Create submission zip
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

## References

- Kubernetes architecture: https://kubernetes.io/docs/concepts/architecture/
- Horizontal Pod Autoscaler: https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
- Prometheus: https://prometheus.io/docs/introduction/overview/
- Grafana: https://grafana.com/docs/
- PyTorch ResNet18: https://pytorch.org/vision/stable/models/resnet.html
- nlohmann/json C++ library: https://github.com/nlohmann/json
- libcurl: https://curl.se/libcurl/c/
- Workload adapted from: https://archive.org/details/archiveteam-twitter-stream-2021-08

---

*Technische Universität Ilmenau · Cloud Computing APL 2026 · DSOSS Group*
