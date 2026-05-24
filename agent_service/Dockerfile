FROM python:3.10-slim

WORKDIR /app

# 安装curl给healthcheck用
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent_core.py .

RUN useradd -m appuser
USER appuser

EXPOSE 8080

CMD ["uvicorn", "agent_core:app", "--host", "0.0.0.0", "--port", "8080"]
