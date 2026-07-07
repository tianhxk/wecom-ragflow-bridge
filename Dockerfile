FROM python:3.12-slim

ARG APP_VERSION=1.0
ENV APP_VERSION=$APP_VERSION
LABEL org.opencontainers.image.title="wecom-ragflow-bridge" \
      org.opencontainers.image.version=$APP_VERSION

WORKDIR /opt/app

COPY requirements.txt .
COPY VERSION .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/* ./config/
COPY config/.env.example ./src/

CMD ["python", "-u", "src/main.py"]
