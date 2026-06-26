#!/usr/bin/env python3
"""
Load test runner for Elastic ML Inference experiments.
Reads workload.txt (requests per second per step).
Records p99 latency and replica count every 15 seconds.
No external load tester dependency needed.
"""

import asyncio
import aiohttp
import time
import json
import csv
import os
import sys
import argparse
import threading
import subprocess
import requests

# ── Configuration ────────────────────────────────────────────
DISPATCHER_URL = "http://192.168.49.2:30001"
PROMETHEUS_URL = "http://192.168.49.2:30090"
RESULTS_DIR    = os.path.join(os.path.dirname(
                     os.path.abspath(__file__)), "../results")
IMAGE_FILE     = os.path.join(os.path.dirname(
                     os.path.abspath(__file__)),
                     "../inference-service/test.jpg")
WORKLOAD_FILE  = os.path.join(os.path.dirname(
                     os.path.abspath(__file__)), "workload.txt")

# ── Helpers ──────────────────────────────────────────────────
def load_workload():
    with open(WORKLOAD_FILE) as f:
        return [int(x) for x in f.read().split()]

def query_prometheus(promql):
    try:
        r = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": promql}, timeout=5)
        j = r.json()
        if j["status"] != "success":
            return None
        results = j["data"]["result"]
        if not results:
            return None
        val = results[0]["value"][1]
        if val in ("NaN", "nan", "+Inf", "-Inf"):
            return None
        return float(val)
    except Exception:
        return None

def get_replicas():
    try:
        r = subprocess.run(
            ["kubectl", "get", "deployment",
             "inference-deployment",
             "-o", "jsonpath={.status.readyReplicas}"],
            capture_output=True, text=True)
        v = r.stdout.strip()
        return int(v) if v else 0
    except Exception:
        return 0

# ── Metrics collector (background thread) ────────────────────
def collect_metrics(stop_event, log):
    while not stop_event.is_set():
        ts      = time.time()
        elapsed = ts - log["start"]
        p99     = query_prometheus(
            "histogram_quantile(0.99,"
            "rate(dispatcher_request_latency_seconds_bucket[1m]))")
        replicas = get_replicas()
        queue    = query_prometheus("dispatcher_queue_depth") or 0.0

        row = {
            "timestamp":   ts,
            "elapsed":     round(elapsed, 1),
            "p99_latency": round(p99, 4) if p99 else None,
            "replicas":    replicas,
            "queue_depth": round(queue, 1),
        }
        log["rows"].append(row)

        p99s = f"{p99:.3f}s" if p99 else "N/A  "
        print(f"  [metrics] t={elapsed:6.0f}s  "
              f"p99={p99s}  replicas={replicas}  queue={queue:.0f}")

        stop_event.wait(15)

# ── Single request ────────────────────────────────────────────
async def send_one(session, image_bytes):
    start = time.time()
    try:
        form = aiohttp.FormData()
        form.add_field("file", image_bytes,
                       filename="img.jpg",
                       content_type="image/jpeg")
        async with session.post(
                f"{DISPATCHER_URL}/predict",
                data=form,
                timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json()
            lat  = time.time() - start
            return {"ok": True, "latency": lat,
                    "label": data.get("label", "?")}
    except Exception as e:
        return {"ok": False, "latency": time.time()-start,
                "error": str(e)}

# ── Main load loop ────────────────────────────────────────────
async def run_load(workload, name):
    print(f"\n{'='*54}")
    print(f"  Experiment : {name}")
    print(f"  Steps      : {len(workload)}  (~{len(workload)}s)")
    print(f"  Max RPS    : {max(workload)}")
    print(f"  Avg RPS    : {sum(workload)/len(workload):.1f}")
    print(f"{'='*54}\n")

    with open(IMAGE_FILE, "rb") as f:
        img = f.read()

    stop   = threading.Event()
    log    = {"start": time.time(), "rows": []}
    thread = threading.Thread(
        target=collect_metrics, args=(stop, log), daemon=True)
    thread.start()

    total = 0
    violations = 0

    connector = aiohttp.TCPConnector(limit=200)
    async with aiohttp.ClientSession(connector=connector) as session:
        for idx, rps in enumerate(workload):
            step_start = time.time()

            # Fire rps concurrent requests
            tasks   = [send_one(session, img) for _ in range(rps)]
            results = await asyncio.gather(*tasks)

            for r in results:
                total += 1
                if r["latency"] > 0.5:
                    violations += 1

            # Log progress every 30 steps
            if idx % 30 == 0:
                pct = violations/max(total,1)*100
                print(f"  [load] step={idx:4d}  rps={rps:3d}  "
                      f"sent={total:5d}  "
                      f"violations={violations} ({pct:.1f}%)")

            # Sleep to fill the 1-second window
            elapsed = time.time() - step_start
            await asyncio.sleep(max(0, 1.0 - elapsed))

    stop.set()
    thread.join(timeout=5)

    comp = (1 - violations/max(total,1)) * 100
    print(f"\n  ── Summary ──────────────────────────────")
    print(f"  Total requests  : {total}")
    print(f"  SLO violations  : {violations}")
    print(f"  SLO compliance  : {comp:.1f}%  (target >99%)")
    print(f"  ─────────────────────────────────────────\n")

    return log

# ── Save CSV ──────────────────────────────────────────────────
def save_csv(name, log):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR,
                        f"{name.replace(' ','_').lower()}.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "timestamp","elapsed",
            "p99_latency","replicas","queue_depth"])
        w.writeheader()
        w.writerows(log["rows"])
    print(f"  Saved: {path}")
    return path

# ── Entry point ───────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument("experiment",
                   choices=["custom","hpa70","hpa90"],
                   help="Which experiment to run")
    args = p.parse_args()

    # Verify image exists
    if not os.path.exists(IMAGE_FILE):
        print(f"ERROR: image not found at {IMAGE_FILE}")
        print("Run: curl -L -o inference-service/test.jpg "
              "https://raw.githubusercontent.com/EliSchwartz/"
              "imagenet-sample-images/master/"
              "n01530575_brambling.JPEG")
        sys.exit(1)

    workload = load_workload()
    print(f"Workload loaded: {len(workload)} steps")

    log = asyncio.run(run_load(workload, args.experiment))
    save_csv(args.experiment, log)
    print(f"Experiment '{args.experiment}' complete.\n")

if __name__ == "__main__":
    main()
