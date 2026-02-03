FROM python:3.12-slim

WORKDIR /app

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/

ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

CMD ["python", "server/remote_mcp.py"]
