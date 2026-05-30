FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py

EXPOSE 8000
# Shell form so UVICORN_WORKERS expands. Multiple workers give the target
# headroom so it does not become the bottleneck under load; the app is
# stateless (injection is per-request random), so workers are independent.
ENV UVICORN_WORKERS=2
CMD uvicorn app:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS}
