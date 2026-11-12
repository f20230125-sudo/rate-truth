FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RATE_TRUTH_RETRIEVAL=bm25 \
    RATE_TRUTH_MARKET_DIR=/tmp/rate-truth/market \
    RATE_TRUTH_LLM_DB=/tmp/rate-truth/llm.sqlite
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /tmp/rate-truth/market \
    && chown -R app:app /tmp/rate-truth
COPY --chown=app:app rate_truth ./rate_truth
COPY --chown=app:app data ./data
COPY --chown=app:app docs/supplier-model.md ./docs/supplier-model.md
COPY --chown=app:app eval/results.json ./eval/results.json
USER app
EXPOSE 8000
CMD ["uvicorn", "rate_truth.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
