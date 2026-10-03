FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home stockroom && mkdir /data && chown stockroom:stockroom /data
COPY app.py .
ENV STOCKROOM_DB=/data/stockroom.db PORT=8000 PYTHONUNBUFFERED=1
USER stockroom
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn 'app:create_app()' --bind 0.0.0.0:${PORT} --workers 2 --threads 2 --timeout 30 --access-logfile -"]
