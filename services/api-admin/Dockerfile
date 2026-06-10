FROM python:3.12-slim

WORKDIR /app

COPY libs/auth /libs/auth
ENV PYTHONPATH=/libs/auth

COPY services/api-admin/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/api-admin .

EXPOSE 8001

CMD ["uvicorn", "admin_api.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
