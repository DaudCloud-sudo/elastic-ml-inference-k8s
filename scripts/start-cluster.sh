#!/bin/bash
set -e

echo "==> Starting Minikube..."
minikube start

echo "==> Checking if images exist..."
eval $(minikube docker-env)
if ! docker images | grep -q "inference-service"; then
    echo "==> Images missing, rebuilding..."
    docker build -t inference-service:v1 \
        ~/cc-project/elastic-ml-inference/inference-service/
    docker build -t dispatcher:v1 \
        ~/cc-project/elastic-ml-inference/dispatcher/
fi
eval $(minikube docker-env -u)

echo "==> Applying all manifests..."
kubectl apply -f ~/cc-project/elastic-ml-inference/k8s-manifests/

echo "==> Waiting for pods..."
kubectl wait --for=condition=ready pod --all --timeout=120s

echo "==> All pods ready:"
kubectl get pods

echo ""
echo "Services available at:"
echo "  Dispatcher:  http://$(minikube ip):30001"
echo "  Prometheus:  http://$(minikube ip):30090"
echo "  Grafana:     http://$(minikube ip):30300"
