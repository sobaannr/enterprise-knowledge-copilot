FROM python:3.12-slim
ARG INSTALL_RETRIEVAL=false
ARG INSTALL_OCR=false
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md requirements.lock ./
COPY copilot ./copilot
RUN pip install --no-cache-dir -c requirements.lock . && \
    if [ "$INSTALL_RETRIEVAL" = "true" ]; then pip install --no-cache-dir -c requirements.lock '.[retrieval]'; fi && \
    if [ "$INSTALL_OCR" = "true" ]; then apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && pip install --no-cache-dir '.[pdf]' && rm -rf /var/lib/apt/lists/*; fi && \
    useradd --create-home copilot && mkdir -p /app/data && chown -R copilot:copilot /app
USER copilot
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "copilot.api:app", "--host", "0.0.0.0", "--port", "8000"]
