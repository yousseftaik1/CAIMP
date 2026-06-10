FROM python:3.12-slim

WORKDIR /app

# System deps for psutil (proc filesystem, network stats)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default data directory (override via CAIMP_DATA_DIR)
RUN mkdir -p /etc/caimp-agent && chmod 700 /etc/caimp-agent

ENV CAIMP_DATA_DIR=/etc/caimp-agent \
    LOG_LEVEL=INFO

ENTRYPOINT ["python", "main.py"]
