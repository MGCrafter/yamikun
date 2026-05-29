FROM python:3.12-slim

# Keine .pyc-Dateien, ungepufferte Logs (damit CapRover-Logs sofort erscheinen).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /app

# Zuerst nur die Requirements kopieren → Docker-Layer-Cache nutzt das aus.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Restlichen Code kopieren (siehe .dockerignore für Ausnahmen).
COPY . .

# Persistente Daten (DB, config.json, hochgeladene Bilder) liegen unter /data.
# In CapRover ein "Persistent Directory" auf /data mappen!
RUN mkdir -p /data
VOLUME ["/data"]

# Web-Panel-Port (muss in CapRover als "Container HTTP Port" gesetzt werden).
EXPOSE 8080

CMD ["python", "-u", "bot.py"]
