#!/usr/bin/env python3
"""
Load test runner for Elastic ML Inference experiments.
Uses barazmoon load tester with workload.txt pattern.
Records p99 latency and replica count over time.
"""

import asyncio
import time
import json
import csv
import os
import sys
import argparse
import threading
import requests
from datetime import datetime

# barazmoon is the actual module name for load_tester package
from barazmoon import MLServerLoad

# ── Configuration ──────────────────────────────────────────
DISPATCHER_URL  = "http://192.168.49.2:30001"
PROMETHEUS_URL  = "http://192.168.49.2:30090"
WORKLOAD_FILE   = os.path.join(os.path.dirname(__file__), "workload.txt")
IMAGE_FILE      = os.path.join(
    os.path.dirname(__file__),
    "../inference-service/test.jpg")
RESULTS_DIR     = os.path.join(
    os.path.dirname(__file__), "../results")

def load_workload(path):
    """Load space-separated integers from workload.txt"""
    with open(path) as f:
        return [int(x) for x in f.read().split()]

def query_prometheus(promql):
    """Query Prometheus HTTP API, return float or None"""
    try:
        r = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": promql},
            timeout=5)
        j = r.json()
        if j["status"] != "success":
            return None
        results = j["data"]["result"]
        if not results:
            return None
        val = results[0]["value"][1]
        if val in ("NaN", "nan", "+Inf"):
            return None
        return float(val)
    except Exception:
        return None

def get_replica_count():
    """Get current inference deployment replica count"""
    try:
        import subprocess
        result = subprocess.run(
            ["kubectl", "get", "deployment",
             "inference-deployment",
             "-o", "jsonpath={.status.readyReplicas}"],
            capture_output=True, text=True)
        val = result.stdout.strip()
        return int(val) if val else 0
    except Exception:
        return 0

def collect_metrics(experiment_name, stop_event, metrics_log):
    """Background thread: collect metrics every 15 seconds"""
    print(f"  [metrics] collector started for {experiment_name}")
    while not stop_event.is_set():
        ts = time.time()
        p99 = query_prometheus(
            "histogram_quantile(0.99, "
            "rate(dispatcher_request_latency_seconds_bucket[1m]))")
        replicas = get_replica_count()
        queue = query_prometheus("dispatcher_queue_depth")

        entry = {
            "timestamp": ts,
            "elapsed":   ts - metrics_log["start_time"],
            "p99_latency": p99,
            "replicas":    replicas,
            "queue_depth": queue,
        }
        metrics_log["data"].append(entry)

        p99_str = f"{p99:.3f}s" if p99 else "N/A"
        print(f"  [metrics] t={entry['elapsed']:.0f}s "
              f"p99={p99_str} "
              f"replicas={replicas} "
              f"queue={queue or 0:.0f}")

        stop_event.wait(15)

async def run_load_test(workload, experiment_name):
    """Send requests following the workload pattern"""
    print(f"\n{'='*50}")
    print(f"  Experiment: {experiment_name}")
    print(f"  Workload steps: {len(workload)}")
    print(f"  Total duration: ~{len(workload)}s")
    print(f"{'='*50}")

    # Read image once
    with open(IMAGE_FILE, "rb") as f:
        image_bytes = f.read()

    # Metrics collection in background thread
    stop_event  = threading.Event()
    metrics_log = {
        "start_time": time.time(),
        "data": []
    }
    metrics_thread = threading.Thread(
        target=collect_metrics,
        args=(experiment_name, stop_event, metrics_log),
        daemon=True)
    metrics_thread.start()

    # Send requests following workload pattern
    # Each number = requests to send in that 1-second window
    request_count = 0
    slo_violations = 0

    for step_idx, rps in enumerate(workload):
        step_start = time.time()

        # Launch 'rps' concurrent requests for this second
        tasks = []
        for _ in range(rps):
            tasks.append(send_request(image_bytes))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, dict):
                request_count += 1
                if r.get("latency", 0) > 0.5:
                    slo_violations += 1

        # Sleep remainder of the second
        elapsed = time.time() - step_start
        sleep_time = max(0, 1.0 - elapsed)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

        if step_idx % 30 == 0:
            print(f"  [load] step {step_idx}/{len(workload)} "
                  f"rps={rps} total_sent={request_count}")

    # Stop metrics collection
    stop_event.set()
    metrics_thread.join(timeout=5)

    # Summary
    slo_rate = (1 - slo_violations/max(request_count,1)) * 100
    print(f"\n  Total requests:    {request_count}")
    print(f"  SLO violations:    {slo_violations}")
    print(f"  SLO compliance:    {slo_rate:.1f}%")

    return metrics_log

async def send_request(image_bytes):
    """Send one prediction request, return latency"""
    import aiohttp
    start = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field("file", image_bytes,
                          filename="image.jpg",
                          content_type="image/jpeg")
            async with session.post(
                f"{DISPATCHER_URL}/predict",
                data=form,
                timeout=aiohttp.ClientTimeout(total=30)) as resp:
                data = await resp.json()
                latency = time.time() - start
                return {"latency": latency, "label": data.get("label")}
    except Exception as e:
        return {"error": str(e), "latency": time.time() - start}

def save_results(experiment_name, metrics_log):
    """Save metrics to CSV for plotting"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    safe_name = experiment_name.replace(" ", "_").lower()
    csv_path = os.path.join(RESULTS_DIR, f"{safe_name}.csv")

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "elapsed",
            "p99_latency", "replicas", "queue_depth"])
        writer.writeheader()
        writer.writerows(metrics_log["data"])

    print(f"  Results saved: {csv_path}")
    return csv_path

def main():
    parser = argparse.ArgumentParser(
        description="Run load test experiment")
    parser.add_argument("experiment",
        help="Name: 'custom', 'hpa70', 'hpa90'")
    args = parser.parse_args()

    workload = load_workload(WORKLOAD_FILE)
    print(f"Loaded workload: {len(workload)} steps, "
          f"max={max(workload)} rps, "
          f"avg={sum(workload)/len(workload):.1f} rps")

    # Run experiment
    metrics_log = asyncio.run(
        run_load_test(workload, args.experiment))

    # Save results
    save_results(args.experiment, metrics_log)
    print(f"\nExperiment '{args.experiment}' complete.")

if __name__ == "__main__":
    main()
