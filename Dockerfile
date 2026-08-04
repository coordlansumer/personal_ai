FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    HF_HUB_DISABLE_XET=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m -u 1000 appuser

ENV FASTEMBED_CACHE_DIR=/app/fastembed-cache
RUN mkdir -p "$FASTEMBED_CACHE_DIR" && chown -R appuser:appuser /app

USER appuser
# Bake the embedding model into the image so runtime never hits the network.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-zh-v1.5', cache_dir='/app/fastembed-cache')"

WORKDIR /app
# Copy app code AFTER the bake so backend edits don't re-download the model.
COPY --chown=appuser:appuser backend/ ./backend/

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
