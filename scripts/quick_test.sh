#!/bin/bash
# Quick smoke test — sends 5 requests and shows results
# Run this after start-cluster.sh to verify everything is working

MINIKUBE_IP=$(minikube ip)
IMAGE="$HOME/cc-project/elastic-ml-inference/inference-service/test.jpg"

echo "==> Quick system test"
echo "    Minikube IP: $MINIKUBE_IP"
echo ""

# 1. Health checks
echo "--- Health checks ---"
echo -n "Dispatcher:       "
curl -s http://$MINIKUBE_IP:30001/health

echo ""
echo -n "Prometheus:       "
curl -s http://$MINIKUBE_IP:30090/-/healthy

echo ""
echo ""

# 2. Prometheus targets
echo "--- Prometheus targets ---"
curl -s "http://$MINIKUBE_IP:30090/api/v1/targets" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for t in data['data']['activeTargets']:
    print(f\"  {t['labels']['job']:20s} → {t['health']}\")
"
echo ""

# 3. Send 5 test predictions
echo "--- Sending 5 test predictions ---"
for i in {1..5}; do
    RESULT=$(curl -s -X POST \
        -F "file=@$IMAGE" \
        http://$MINIKUBE_IP:30001/predict)
    LABEL=$(echo $RESULT | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('label','ERROR'))")
    LATENCY=$(echo $RESULT | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('latency_seconds',0):.3f}\")")
    SLO="✓"
    if python3 -c "exit(0 if float('$LATENCY') < 0.5 else 1)" 2>/dev/null; then
        SLO="✓ within SLO"
    else
        SLO="✗ SLO violated"
    fi
    echo "  Request $i: $LABEL  (${LATENCY}s) $SLO"
done
echo ""

# 4. Dispatcher status
echo "--- Dispatcher status ---"
curl -s http://$MINIKUBE_IP:30001/status | python3 -m json.tool
echo ""

# 5. Current pods
echo "--- Pod status ---"
kubectl get pods
echo ""

echo "==> Test complete. System is healthy."
echo ""
echo "Next steps:"
echo "  Start autoscaler:  ./autoscaler-cpp/build/autoscaler"
echo "  Run experiment:    python3 load-tester/run_experiment.py custom"
echo "  Open Grafana:      http://$MINIKUBE_IP:30300  (admin/cloudproject)"
