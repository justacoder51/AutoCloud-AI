FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080 PYTHONPATH=/app
WORKDIR /app
COPY requirements.txt requirements-dashboard.txt requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt \
    && useradd --create-home --uid 10001 appuser
COPY app ./app
COPY config/dashboard-evaluation.json ./config/dashboard-evaluation.json
COPY config/measured-validation.json ./config/measured-validation.json
COPY models/runs/20261116T051914Z_48d41482 ./models/runs/20261116T051914Z_48d41482
USER appuser
EXPOSE 8080
CMD ["sh", "-c", "if [ \"$AUTOCLOUD_COMPONENT\" = dashboard ]; then exec streamlit run app/dashboard/home.py --server.address=0.0.0.0 --server.port=${PORT} --server.headless=true --browser.gatherUsageStats=false; else exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}; fi"]
