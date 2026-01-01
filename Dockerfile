FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    procps coreutils && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY covert_protocol.py mqtt_bot.py mqtt_controller.py mqtt_monitor.py ./

RUN chmod +x mqtt_bot.py mqtt_controller.py mqtt_monitor.py

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-u"]
CMD ["mqtt_bot.py"]
