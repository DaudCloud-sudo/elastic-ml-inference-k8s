import io
import time

import torch
from torchvision.models import resnet18, ResNet18_Weights
from PIL import Image
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# ---------------------------------------------------------------------
# Model loading (happens once, at startup — NOT per request)
# ---------------------------------------------------------------------
DEVICE = torch.device("cpu")  # Explicit: enforce CPU-only execution

# Limit PyTorch's internal thread usage to match the K8s CPU limit (1 core).
# Without this, PyTorch may spawn threads equal to the host's core count,
# which would be misleading in a container limited to 1 CPU.
torch.set_num_threads(1)

weights = ResNet18_Weights.IMAGENET1K_V1
model = resnet18(weights=weights)
model.eval()  # Inference mode: disables dropout, fixes batchnorm stats
model.to(DEVICE)

preprocess = weights.transforms()
categories = weights.meta["categories"]

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve_ui():
    return FileResponse("static/index.html")

@app.get("/health")
def health():
    """Simple liveness/readiness check endpoint."""
    return {"status": "ok"}


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    start = time.time()

    # Read and decode the uploaded image
    image_bytes = await file.read()
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # Preprocess: resize, center-crop, normalize (matches ImageNet training)
    input_tensor = preprocess(image).unsqueeze(0).to(DEVICE)

    # Inference — no_grad disables gradient tracking (saves memory/compute)
    with torch.no_grad():
        output = model(input_tensor).squeeze(0)

    # Get top-1 prediction
    top1_idx = output.argmax().item()
    label = categories[top1_idx]

    latency = time.time() - start

    return JSONResponse({
        "label": label,
        "latency_seconds": latency
    })