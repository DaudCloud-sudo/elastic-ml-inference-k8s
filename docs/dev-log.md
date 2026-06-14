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
