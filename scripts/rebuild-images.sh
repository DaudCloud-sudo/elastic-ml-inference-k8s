#!/bin/bash
set -e

echo "==> Pointing docker CLI at Minikube daemon..."
eval $(minikube docker-env)

echo "==> Building inference-service:v1..."
docker build -t inference-service:v1 \
  ~/cc-project/elastic-ml-inference/inference-service/

echo "==> Building dispatcher:v1..."
docker build -t dispatcher:v1 \
  ~/cc-project/elastic-ml-inference/dispatcher/

echo "==> Verifying images exist:"
docker images | grep -E "inference-service|dispatcher"

echo "==> Reverting to host docker daemon..."
eval $(minikube docker-env -u)

echo "==> All done. Safe to kubectl apply now."
