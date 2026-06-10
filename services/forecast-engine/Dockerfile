FROM python:3.12-slim

WORKDIR /app

COPY libs/nats_client /libs/nats_client
ENV PYTHONPATH=/libs/nats_client

COPY services/forecast-engine/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/forecast-engine .

CMD ["python", "-m", "forecast_engine.main"]
