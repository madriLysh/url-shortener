FROM python:3.11-slim AS builder

WORKDIR /build

RUN python -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"



COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv
 
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY . .


EXPOSE 8000

CMD ["uvicorn", "--factory", "main:build_application", "--host", "0.0.0.0", "--port", "8000"] 