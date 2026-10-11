FROM python:3.11-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 TF_CPP_MIN_LOG_LEVEL=2
COPY requirements.txt .
RUN sed -i 's/^tensorflow>/tensorflow-cpu>/' requirements.txt && pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p data/uploads models outputs
EXPOSE 8000
# 1 seul worker : l'état d'entraînement est conservé en mémoire
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
