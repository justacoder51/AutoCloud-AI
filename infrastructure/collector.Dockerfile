FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt requirements-monitoring.txt ./
RUN pip install --no-cache-dir -r requirements-monitoring.txt \
    && useradd --create-home --uid 10001 appuser
COPY app ./app
USER appuser
ENTRYPOINT ["python", "-m", "app.data.collector"]
CMD ["--minutes=30", "--output=/tmp/metrics.ndjson"]
