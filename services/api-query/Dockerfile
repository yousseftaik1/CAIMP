FROM python:3.12-slim

WORKDIR /app

COPY libs/auth /libs/auth
ENV PYTHONPATH=/libs/auth

COPY services/api-query/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/api-query .

EXPOSE 8002

CMD ["uvicorn", "query_api.main:app", "--host", "0.0.0.0", "--port", "8002", "--log-level", "info"]
