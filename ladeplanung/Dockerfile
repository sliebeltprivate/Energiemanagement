FROM python:3.12-slim

ENV LADEPLANUNG_DATA=/data \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod a+x /app/run.sh

CMD ["/app/run.sh"]
