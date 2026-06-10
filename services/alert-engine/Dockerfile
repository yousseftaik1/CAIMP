FROM python:3.12-slim

WORKDIR /app

COPY libs/nats_client /libs/nats_client
ENV PYTHONPATH=/libs/nats_client

COPY services/alert-engine/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/alert-engine .

CMD ["python", "-m", "alert_engine.main"]
