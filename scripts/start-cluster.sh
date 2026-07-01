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

echo "==> Downloading test image if missing..."
if [ ! -f ~/cc-project/elastic-ml-inference/inference-service/test.jpg ]; then
    curl -L -o ~/cc-project/elastic-ml-inference/inference-service/test.jpg \
      "https://raw.githubusercontent.com/EliSchwartz/imagenet-sample-images/master/n01530575_brambling.JPEG"
    echo "  test.jpg downloaded"
else
    echo "  test.jpg already exists"
fi

echo "==> Applying core manifests (no HPA)..."
kubectl apply -f ~/cc-project/elastic-ml-inference/k8s-manifests/

echo "==> Removing any leftover HPA from previous experiments..."
kubectl delete hpa --all 2>/dev/null || true

echo "==> Resetting inference to 1 replica..."
kubectl scale deployment/inference-deployment --replicas=1

echo "==> Waiting for pods..."
kubectl wait --for=condition=ready pod --all --timeout=180s

echo ""
echo "==> All pods ready:"
kubectl get pods

echo ""
echo "Services available at:"
echo "  Dispatcher:  http://$(minikube ip):30001"
echo "  Prometheus:  http://$(minikube ip):30090"
echo "  Grafana:     http://$(minikube ip):30300"
echo ""
echo "Quick health check:"
sleep 3
curl -s http://$(minikube ip):30001/health && echo ""
echo "==> System ready."
