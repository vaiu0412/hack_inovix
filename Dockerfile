# DEPORT – Streamlit app. Everything that changes (database, voice notes, backups) lives on the /data volume;
# the image only holds code and the read-only demo data. Runs as root so hosted disks (Render, Railway) mounted at
# /data are writable without extra setup.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_PATH=/data/deport.db \
    PORT=8501

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT', '8501') + '/_stcore/health', timeout=4)"

# shell form so $PORT (set by Render / Railway) is used; exec so Streamlit gets stop signals.
# A Render "Secret File" named secrets.toml (/etc/secrets) is used for Google sign-in when present.
CMD if [ -f /etc/secrets/secrets.toml ]; then cp /etc/secrets/secrets.toml .streamlit/secrets.toml; fi; \
    exec streamlit run app.py --server.port="${PORT}" --server.address=0.0.0.0 --server.headless=true
