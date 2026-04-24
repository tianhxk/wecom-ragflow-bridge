FROM python:3.12-slim

WORKDIR /opt/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/* ./config/
COPY config/.env.example ./src/

CMD ["python", "-u", "src/main.py"]
