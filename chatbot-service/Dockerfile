# FAQ chatbot service with E-Branchformer voice input.
# Build:  docker build -t org-faq-chatbot .
# Run:    docker run --env-file .env -p 8000:8000 org-faq-chatbot
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    PORT=8000

RUN useradd --create-home --uid 1000 app && mkdir -p /models && chown app /models
WORKDIR /app

# CPU-only PyTorch first, so pip does not pull the much larger CUDA build.
COPY requirements.txt requirements-ml.txt ./
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.11.*" "torchaudio==2.11.*" \
 && pip install -r requirements-ml.txt

COPY app ./app
COPY scripts ./scripts

USER app
# Bake the models into the image so cold starts do not download ~0.5 GB.
# Build with --build-arg PRELOAD_MODELS=false to download on first start instead.
ARG PRELOAD_MODELS=true
RUN if [ "$PRELOAD_MODELS" = "true" ]; then python scripts/download_models.py; fi

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4)"

# --no-access-log: client addresses are not written to the server log (NFR-CMP-01).
CMD ["sh", "-c", "exec uvicorn app.main:app_factory --factory --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
