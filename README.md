# Elastic ML Inference Serving on Kubernetes

**Course:** Cloud Computing (APL) — Technische Universität Ilmenau
**Group/Author:** DaudCloud-Sudo

## Project Overview

This project implements an elastic, autoscaling image classification
inference service deployed on a local Kubernetes (Minikube) cluster.

The service uses a pre-trained ResNet18 model (PyTorch) to classify
images submitted as queries. The system must maintain a server-side
latency SLO of **< 0.5s (p99)**.

A **custom autoscaler, written in C++**, monitors the cluster via
Prometheus and dynamically adjusts the number of inference service
replicas (horizontal scaling) to meet the SLO while minimizing
allocated CPU cores.

## Architecture
Load Tester -> Dispatcher -> [ML Inference Replica 1..N]

^                    |

|                    v

Autoscaler (C++) <- Monitoring (Prometheus)

|

v

K8s API server (scales Deployment)
## Components

| Component | Tech | Status |
|---|---|---|
| ML Inference Service | Python, FastAPI, PyTorch (ResNet18) | 🚧 In progress |
| Dispatcher | TBD | ⬜ Not started |
| Monitoring | Prometheus + exporters | ⬜ Not started |
| Custom Autoscaler | C++ | ⬜ Not started |
| Load Tester | reconfigurable-ml-pipeline/load_tester | ⬜ Not started |

## Constraints

- Local Minikube cluster only (4 CPUs, 8GB RAM)
- Inference runs on CPU only (no GPU)
- Each ML replica: CPU request = limit = 1 core
- No Kubernetes HPA in final solution — custom C++ autoscaler instead
- Final comparison: custom autoscaler vs. HPA (70% and 90% CPU target)

## Setup

See `docs/setup.md` for environment setup instructions.

## Development Log

See `docs/dev-log.md` for ongoing notes and decisions.
