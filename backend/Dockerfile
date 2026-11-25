FROM python:3.12-slim

WORKDIR /app

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
COPY backend/sim ./sim
COPY backend/agents ./agents
COPY backend/memory ./memory
COPY backend/llm ./llm
COPY backend/api ./api
COPY frontend/public/assets/map.json /app/assets/map.json

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu .

RUN mkdir -p /app/data /app/logs

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MAP_PATH=/app/assets/map.json \
    DATABASE_URL=sqlite+aiosqlite:////app/data/ai_village.db \
    REPLAY_LOG_DIR=/app/logs \
    LLM_PROVIDER=mock \
    EMBEDDING_PROVIDER=auto

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
