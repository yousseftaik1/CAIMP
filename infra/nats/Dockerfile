FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir nats-py==2.7.2

COPY setup_streams.py .

CMD ["python", "setup_streams.py"]
