FROM python:3.12-slim

WORKDIR /app

COPY libs/nats_client /libs/nats_client
ENV PYTHONPATH=/libs/nats_client

COPY services/ws-gateway/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/ws-gateway .

EXPOSE 8080

CMD ["uvicorn", "ws_gateway.main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]
