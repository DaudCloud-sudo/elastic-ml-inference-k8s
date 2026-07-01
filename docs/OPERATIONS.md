# Operations Guide — Elastic ML Inference Serving

Complete reference for running this system from a cold Ubuntu machine
through to full experiment results. See README.md for project overview.

---

## Quick Start (after first-time setup)

```bash
# Every time after reboot — one command does everything
./scripts/start-cluster.sh

# Verify system health
./scripts/quick_test.sh

# Build C++ autoscaler if not already built
cd autoscaler-cpp/build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j4
cd ~/cc-project/elastic-ml-inference

# Run experiments (each ~10 minutes)
source ~/cc-project/venv/bin/activate
python3 load-tester/run_experiment.py custom   # Terminal 1: run autoscaler first
python3 load-tester/run_experiment.py hpa70    # apply hpa-70.yaml first
python3 load-tester/run_experiment.py hpa90    # apply hpa-90.yaml first

# Generate plots
python3 results/plot_detailed.py
```

---

## Service URLs

| Service | URL | Login |
|---|---|---|
| Inference GUI | http://localhost:8080 | none (port-forward required) |
| Dispatcher | http://192.168.49.2:30001 | none |
| Prometheus | http://192.168.49.2:30090 | none |
| Grafana | http://192.168.49.2:30300 | admin / cloudproject |

```bash
# Inference GUI port-forward (keep terminal open)
kubectl port-forward deployment/inference-deployment 8080:8000
```

---

## Docker Commands Reference

```bash
# Which daemon am I talking to?
docker info | grep "Docker Root"

# Point at Minikube's daemon (required before docker build)
eval $(minikube docker-env)

# Restore host daemon
eval $(minikube docker-env -u)

# List images in current daemon
docker images

# Build an image
docker build -t <name>:<tag> <directory>

# Run container locally for testing
docker run --rm -p 8000:8000 --cpus=1 inference-service:v1

# Container logs
docker logs <container-id>
```

---

## Minikube Commands Reference

```bash
minikube start --cpus=4 --memory=8192   # first start / after delete
minikube start                           # resume after stop/reboot
minikube stop                            # pause (preserves state)
minikube delete                          # destroy everything
minikube status                          # check health
minikube ip                              # get node IP
minikube addons enable metrics-server    # required for HPA
minikube addons list                     # see what is enabled
minikube ssh                             # SSH into node (debugging)
```

---

## kubectl Commands Reference

```bash
# Pod management
kubectl get pods                              # list pods
kubectl get pods -w                           # watch live
kubectl describe pod <name>                   # full detail + events
kubectl logs <pod-name>                       # stdout
kubectl logs -f <pod-name>                    # follow live
kubectl exec -it <pod> -- bash                # open shell

# Deployment management
kubectl get deployments
kubectl scale deployment/<name> --replicas=N
kubectl rollout restart deployment/<name>
kubectl rollout status deployment/<name>

# Services
kubectl get svc
kubectl port-forward deployment/<name> <host>:<pod>

# HPA
kubectl get hpa
kubectl get hpa --watch
kubectl delete hpa --all

# Apply / delete manifests
kubectl apply -f <file>.yaml
kubectl apply -f <directory>/
kubectl delete -f <file>.yaml

# Cluster-internal test (sends request from inside cluster network)
kubectl run curl-test --image=curlimages/curl -i --tty --rm \
  --restart=Never -- sh
# inside pod: curl http://inference-service:8000/health
```

---

## Experiment Procedures

### Reset between experiments

```bash
kubectl delete hpa --all 2>/dev/null || true
kubectl scale deployment/inference-deployment --replicas=1
kubectl get pods   # confirm 1 inference pod Running
```

### Experiment 1 — Custom C++ autoscaler

Terminal 1:
```bash
./autoscaler-cpp/build/autoscaler
```

Terminal 2:
```bash
source ~/cc-project/venv/bin/activate
python3 load-tester/run_experiment.py custom
```

### Experiment 2 — HPA 70%

```bash
kubectl apply -f k8s-manifests/experiments/hpa-70.yaml
kubectl get hpa --watch        # wait for real CPU %
source ~/cc-project/venv/bin/activate
python3 load-tester/run_experiment.py hpa70
kubectl delete hpa inference-hpa-70
```

### Experiment 3 — HPA 90%

```bash
kubectl apply -f k8s-manifests/experiments/hpa-90.yaml
kubectl get hpa --watch
source ~/cc-project/venv/bin/activate
python3 load-tester/run_experiment.py hpa90
kubectl delete hpa inference-hpa-90
```

### Generate plots

```bash
source ~/cc-project/venv/bin/activate
python3 results/plot_detailed.py
xdg-open results/comparison_final.png
```

---

## Common Errors and Fixes

| Error | Fix |
|---|---|
| `no route to host :8443` | `./scripts/start-cluster.sh` |
| `ErrImageNeverPull` | `./scripts/rebuild-images.sh` |
| `Pending` pod | `kubectl describe pod <name>` check CPU; reduce replicas to 1 |
| `ModuleNotFoundError` | `source ~/cc-project/venv/bin/activate` |
| `<unknown>/70%` on HPA | `minikube addons enable metrics-server` wait 60s |
| Push rejected | `git pull --rebase origin main && git push` |

---

*TU Ilmenau · Cloud Computing APL 2026*
