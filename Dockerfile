# Deployed "brain" server (no browser). Azure Container Apps / Railway builds this.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements-server.txt .
RUN pip install -r requirements-server.txt

COPY . .

EXPOSE 8000

# Azure Container Apps sets $PORT; default to 8000.
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
