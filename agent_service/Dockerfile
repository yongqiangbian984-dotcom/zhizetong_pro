FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent_core.py .

RUN useradd -m appuser
USER appuser

EXPOSE 8080

CMD ["uvicorn", "agent_core:app", "--host", "0.0.0.0", "--port", "8080"]
