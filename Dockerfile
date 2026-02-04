FROM python:3.12-slim

WORKDIR /app

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/

ENV PORT=8000
CMD uvicorn server.remote_mcp:app --host 0.0.0.0 --port $PORT
