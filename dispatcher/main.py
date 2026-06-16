import asyncio
import time
import statistics
import os
from collections import deque

import httpx
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from prometheus_client import Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

# ─────────────────────────────────────────────────────────────
# Configuration — driven by environment variables so we can
# change them in Kubernetes manifests without rebuilding
# ─────────────────────────────────────────────────────────────
INFERENCE_SERVICE_URL = os.getenv(
    "INFERENCE_SERVICE_URL",
    "http://inference-service:8000"   # K8s internal DNS name
)
INITIAL_REPLICAS = int(os.getenv("INITIAL_REPLICAS", "1"))
MAX_QUEUE_SIZE   = int(os.getenv("MAX_QUEUE_SIZE", "500"))
REQUEST_TIMEOUT  = float(os.getenv("REQUEST_TIMEOUT", "10.0"))

# ─────────────────────────────────────────────────────────────
# Prometheus metrics — these are what your C++ autoscaler
# will later query via Prometheus HTTP API
# ─────────────────────────────────────────────────────────────
QUEUE_DEPTH    = Gauge("dispatcher_queue_depth",
                       "Number of requests waiting in the queue")
REPLICA_COUNT  = Gauge("dispatcher_replica_count",
                       "Number of active worker slots (mirrors K8s replicas)")
LATENCY_HIST   = Histogram("dispatcher_request_latency_seconds",
                            "End-to-end request latency as seen by dispatcher",
                            buckets=[.05,.1,.15,.2,.25,.3,.4,.5,.75,1.0,2.0,5.0])

app = FastAPI()

# ─────────────────────────────────────────────────────────────
# Core data structures
# ─────────────────────────────────────────────────────────────
# The queue holds (image_bytes, future) tuples.
# The future is how the HTTP handler waits for the worker's result.
request_queue: asyncio.Queue = None

# Track active workers so we can add/remove them dynamically
workers: list[asyncio.Task] = []

# Rolling window of recent latencies (last 200 requests) for p99
recent_latencies: deque = deque(maxlen=200)


# ─────────────────────────────────────────────────────────────
# Startup: create queue and launch initial workers
# ─────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    global request_queue
    request_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
    QUEUE_DEPTH.set(0)

    for i in range(INITIAL_REPLICAS):
        _launch_worker(i)

    REPLICA_COUNT.set(INITIAL_REPLICAS)
    print(f"Dispatcher started. Workers: {INITIAL_REPLICAS}, "
          f"Target: {INFERENCE_SERVICE_URL}")


def _launch_worker(worker_id: int):
    """Spawn one async worker task."""
    task = asyncio.create_task(_worker_loop(worker_id))
    workers.append(task)
    return task


async def _worker_loop(worker_id: int):
    """
    One worker = one "slot" for one inference replica.
    Runs forever: dequeue → forward to inference → resolve future.

    This is the key design: a worker only picks the NEXT request
    after it has fully received the response from the current one.
    This is what enforces "one request at a time per replica."
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        while True:
            try:
                # Block until a request is available in the queue
                image_bytes, content_type, future = await request_queue.get()
                QUEUE_DEPTH.set(request_queue.qsize())

                start = time.time()
                try:
                    response = await client.post(
                        f"{INFERENCE_SERVICE_URL}/predict",
                        files={"file": ("image", image_bytes, content_type)},
                    )
                    latency = time.time() - start
                    recent_latencies.append(latency)
                    LATENCY_HIST.observe(latency)

                    # Resolve the future so the HTTP handler can return
                    if not future.done():
                        future.set_result({
                            "label": response.json().get("label"),
                            "latency_seconds": latency,
                            "worker_id": worker_id,
                        })
                except Exception as e:
                    latency = time.time() - start
                    if not future.done():
                        future.set_exception(e)

                finally:
                    request_queue.task_done()

            except asyncio.CancelledError:
                # Clean shutdown signal — exit the loop gracefully
                print(f"Worker {worker_id} shutting down.")
                break
            except Exception as e:
                print(f"Worker {worker_id} unexpected error: {e}")
                await asyncio.sleep(0.1)


# ─────────────────────────────────────────────────────────────
# HTTP Endpoints
# ─────────────────────────────────────────────────────────────
@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    """
    Receives an image from the Load Tester.
    Enqueues it and waits for a worker to process it.
    """
    if request_queue.full():
        return JSONResponse(
            {"error": "Queue full — dropping request"},
            status_code=503
        )

    image_bytes  = await file.read()
    content_type = file.content_type or "image/jpeg"

    # A Future is a promise of a result. We create one here and
    # pass it into the queue alongside the image data.
    # The worker will call future.set_result(...) when done,
    # which unblocks the await below.
    loop   = asyncio.get_event_loop()
    future = loop.create_future()

    await request_queue.put((image_bytes, content_type, future))
    QUEUE_DEPTH.set(request_queue.qsize())

    try:
        result = await asyncio.wait_for(future, timeout=REQUEST_TIMEOUT)
        return JSONResponse(result)
    except asyncio.TimeoutError:
        future.cancel()
        return JSONResponse(
            {"error": "Request timed out"},
            status_code=504
        )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "workers": len(workers),
        "queue_depth": request_queue.qsize() if request_queue else 0,
    }


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/status")
def status():
    """Human-readable status — useful for debugging."""
    p99 = None
    if len(recent_latencies) >= 10:
        sorted_lat = sorted(recent_latencies)
        idx = int(0.99 * len(sorted_lat))
        p99 = sorted_lat[idx]

    return {
        "workers":     len(workers),
        "queue_depth": request_queue.qsize() if request_queue else 0,
        "p99_latency": p99,
        "inference_url": INFERENCE_SERVICE_URL,
    }


@app.post("/scale")
async def scale(target_replicas: int):
    """
    Called by your C++ autoscaler to adjust the worker count.
    This is the bridge between K8s replica count and Dispatcher's
    worker count — they must stay in sync.
    """
    current = len(workers)

    if target_replicas > current:
        # Scale up: add workers
        for i in range(current, target_replicas):
            _launch_worker(i)
        REPLICA_COUNT.set(target_replicas)
        return {"scaled": "up", "from": current, "to": target_replicas}

    elif target_replicas < current:
        # Scale down: cancel excess workers
        to_remove = workers[target_replicas:]
        workers[:] = workers[:target_replicas]
        for task in to_remove:
            task.cancel()
        REPLICA_COUNT.set(target_replicas)
        return {"scaled": "down", "from": current, "to": target_replicas}

    return {"scaled": "none", "current": current}