# =============================================================================
# Stage 1 — React-Frontend (Vite) bauen. Node wird NUR hier gebraucht und landet
# NICHT im finalen Image. Erzeugt frontend/dist (statische Dateien).
# =============================================================================
FROM node:22-alpine AS frontend
WORKDIR /app/frontend

# Erst nur die Lockfiles -> Docker-Layer-Cache für npm ci nutzen.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Restlichen Frontend-Quellcode kopieren und bauen.
COPY frontend/ ./
RUN npm run build


# =============================================================================
# Stage 2 — Bot-Image (Python). Liefert über aiohttp die JSON-API + das in
# Stage 1 gebaute Frontend aus (Single-Container).
# =============================================================================
FROM python:3.12-slim

# Keine .pyc-Dateien, ungepufferte Logs (damit CapRover-Logs sofort erscheinen).
# TZ steuert u.a. den täglichen Karten-Limit-Reset (lokale Mitternacht statt UTC).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    TZ=Europe/Vienna

WORKDIR /app

# tzdata für die Zeitzone (slim-Image bringt keine Zonendaten mit).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Zuerst nur die Requirements kopieren → Docker-Layer-Cache nutzt das aus.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Restlichen Code kopieren (siehe .dockerignore für Ausnahmen).
COPY . .

# Gebautes Frontend aus Stage 1 übernehmen. frontend/dist liegt NICHT im Repo,
# sondern wird hier frisch eingespielt → webpanel.py liefert es unter "/" aus.
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Persistente Daten (DB, config.json, hochgeladene Bilder) liegen unter /data.
# In CapRover ein "Persistent Directory" auf /data mappen!
RUN mkdir -p /data
VOLUME ["/data"]

# Web-Panel-Port (muss in CapRover als "Container HTTP Port" gesetzt werden).
EXPOSE 8080

CMD ["python", "-u", "bot.py"]
