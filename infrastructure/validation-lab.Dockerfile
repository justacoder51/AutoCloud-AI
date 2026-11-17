FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080 PYTHONPATH=/app
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.135.3 uvicorn==0.44.0 \
    && useradd --create-home --uid 10001 appuser
COPY app/validation/lab_app.py ./app/validation/lab_app.py
USER appuser
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.validation.lab_app:app --host 0.0.0.0 --port ${PORT} --workers 1"]
