FROM python:3.12-slim

WORKDIR /app

COPY libs/nats_client /libs/nats_client
ENV PYTHONPATH=/libs/nats_client

COPY services/ai-worker/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/ai-worker .

CMD ["python", "-m", "ai_worker.main"]
