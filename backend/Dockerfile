# Single-stage build: the frontend is plain HTML/CSS/JS with no bundler, so
# there's no separate frontend build stage to run.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# torch and faiss each bundle their own OpenMP runtime; see
# backend/app/search.py for why both of these are required at runtime.
ENV PYTHONUNBUFFERED=1 \
    KMP_DUPLICATE_LIB_OK=TRUE \
    OMP_NUM_THREADS=1 \
    HF_HOME=/app/.cache/huggingface

# Bake the CLIP weights into the image at a fixed, known cache path so the
# container never needs network access to download them on startup.
RUN mkdir -p "$HF_HOME" && \
    python -c "import open_clip; open_clip.create_model_and_transforms('ViT-B-32', pretrained='laion2b_s34b_b79k')"

COPY backend/app ./backend/app
COPY frontend ./frontend

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health').status==200 else 1)"

CMD ["uvicorn", "backend.app.main:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "5000"]
