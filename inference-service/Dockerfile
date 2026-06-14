FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (separate layer = better build caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download model weights at build time, not at container startup.
# This avoids a slow first-request and avoids needing internet access
# inside the running pod.
RUN python -c "from torchvision.models import resnet18, ResNet18_Weights; resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)"

# Copy application code
COPY main.py .
COPY static/ static/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]