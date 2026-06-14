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
