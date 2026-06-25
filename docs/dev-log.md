# Development Log

## Phase 0 — Environment Setup
- Installed Docker, kubectl, Minikube on Ubuntu
- Started Minikube: `minikube start --cpus=4 --memory=8192 --driver=docker`
- Enabled metrics-server addon for `kubectl top` sanity checks
- Set up Python venv with fastapi, uvicorn, torch, torchvision, pillow
- Installed C++ toolchain: cmake, libcurl4-openssl-dev, nlohmann-json3-dev
- Created repo structure and git setup

## Phase 1 — FastAPI ResNet18 Inference Service
(notes go here as we build)

## Phase 2 — Dockerization (cont.)
- Fixed docker permission issue: user added to docker group required new
  login session (rebooted), `newgrp docker` is a temporary per-shell fix
- Updated requirements.txt with CPU-only torch/torchvision wheels
  (--extra-index-url https://download.pytorch.org/whl/cpu) — venv's pip freeze
  pulled CUDA wheels by default
- Built image successfully inside Minikube's docker daemon via
  `eval $(minikube docker-env)`
- Verified container runs with --cpus=1 and /predict + GUI work correctly

## Phase 2 — Dockerization (cont.)
- Fixed docker permission issue: user added to docker group required new
  login session (rebooted), `newgrp docker` is a temporary per-shell fix
- Updated requirements.txt with CPU-only torch/torchvision wheels
  (--extra-index-url https://download.pytorch.org/whl/cpu) — venv's pip freeze
  pulled CUDA wheels by default
- Built image successfully inside Minikube's docker daemon via
  `eval $(minikube docker-env)`
- Verified container runs with --cpus=1 and /predict + GUI work correctly

## Phase 3 — K8s Deployment & Service
- Created inference-deployment.yaml (CPU request=limit=1, imagePullPolicy: Never)
- Created inference-service.yaml (ClusterIP, port 8000)
- Hit issue: after host reboot, Minikube cluster was unreachable
  (no route to host on 192.168.49.2:8443) — Minikube didn't auto-resume.
  Fixed with `minikube start`.
- Note: if Minikube recreates the cluster, locally-built images inside its
  docker daemon are lost and must be rebuilt via `eval $(minikube docker-env)`
  before kubectl apply will work (otherwise ErrImageNeverPull)
- Verified inference-service reachable from inside cluster via kube-dns
  (curl http://inference-service:8000/health from a debug pod) — NOT
  resolvable from host shell, which is expected (ClusterIP DNS is
  cluster-internal only)

## Phase 4 — Dispatcher (debugging)
- Hit etcd failure after repeated Minikube restarts:
  apiserver returned 500, etcd health check failed.
  Root cause: Minikube state corruption from repeated unclean stops.
  Fix: `minikube delete` then `minikube start --cpus=4 --memory=8192`
  (nuclear option but cleanest — code is in git, images rebuilt via script)
- Key lesson: minikube delete destroys the cluster but NOT your code.
  Always commit before experimenting with cluster-level changes.
- Created scripts/rebuild-images.sh: rebuilds both Docker images inside
  Minikube's daemon in one command. Run this after every minikube delete.
- Verified full request chain: host curl → NodePort → Dispatcher Pod →
  CoreDNS → ClusterIP → Inference Pod → ResNet18 → response

## Phase 5 — Prometheus + Grafana (complete)
- All 4 pods running: dispatcher, inference, prometheus, grafana
- Prometheus scraping dispatcher at dispatcher-service:8001/metrics every 15s
- Grafana dashboard created with 3 panels:
    queue_depth, replica_count, p99_latency (with 0.5s SLO threshold line)
- Grafana data source: http://prometheus-service:9090 (internal K8s DNS)
- PromQL API verified: GET /api/v1/query returns JSON with
  data.result[0].value[1] = metric value string
- Inference GUI accessible via: kubectl port-forward deployment/inference-deployment 8080:8000
- NodePorts summary:
    Dispatcher:  192.168.49.2:30001 (Load Tester entry point)
    Prometheus:  192.168.49.2:30090 (metrics DB + query API)
    Grafana:     192.168.49.2:30300 (visualization, admin/cloudproject)

## Phase 6 — C++ Autoscaler (fixes)
- Fixed NaN handling: Prometheus returns string "NaN" when
  histogram_quantile has no data (no requests yet after restart).
  std::stod("NaN") produces float NaN silently — now explicitly
  checked and mapped to -1.0 (no-data sentinel value)
- Startup script (scripts/start-cluster.sh) now reliably brings
  up all 4 pods after any Minikube restart in one command
- Autoscaler verified running: connects to Prometheus, parses
  metrics, applies scaling logic every 15 seconds
- Next: load testing with workload.txt to trigger real scaling

## Phase 6 — C++ Autoscaler (K8s scaling fix)
- K8s PATCH via raw HTTP + Bearer token failed (permission/auth issues
  with kubectl create token on Minikube)
- Fix: replaced httpPatch approach with kubectl CLI via popen()
  kubectl already has credentials from ~/.kube/config (set by minikube start)
  cmd: kubectl scale deployment/inference-deployment --replicas=N
- This is cleaner for host-side autoscaler; in-cluster deployment would
  use ServiceAccount RBAC instead
- Verified: kubectl scale works correctly from host
- p99=4.7s observed during 10 concurrent requests to 1 replica —
  expected: queue backs up at dispatcher, sequential processing means
  req 10 waits behind 9 others. Proves scaling is necessary.

## Phase 6 — C++ Autoscaler (final fixes)
- Fixed compile error: literal newline inside string from Python patch script
  (std::cout line was split across two lines by regex replacement)
- kubectl scale verified working manually: deployment scales 1→2→1 in ~2s
- Autoscaler reading real metrics: p99 ~0.19-0.29s under light load
- Sustained load test (200+ requests at 2 req/s): p99 stable ~0.29s
  with 1 replica — confirms single replica handles ~2 req/s within SLO
- Heavy load needed to trigger scale-up (need concurrent requests)
- Installed reconfigurable-ml-pipeline/load_tester for Phase 7

## Phase 7 — Load Testing + Experiments
- MAX_REPLICAS reduced to 2 (Minikube 4 CPU - system overhead = ~2 free)
- Load tester: barazmoon package (import name), not load_tester
- Three experiments run with workload.txt:
    1. custom: C++ autoscaler (latency + queue based)
    2. hpa70:  Kubernetes HPA 70% CPU target
    3. hpa90:  Kubernetes HPA 90% CPU target
- Results saved to results/*.csv
- Comparison plot saved to results/comparison.png
  Shows: p99 latency over time + replica count over time
  Red dashed line = 0.5s SLO boundary
