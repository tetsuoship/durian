FROM python:3.12-slim

WORKDIR /app

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/
COPY scripts/ ./scripts/

ENV PORT=8000
CMD ["python", "server/remote_mcp.py"]
