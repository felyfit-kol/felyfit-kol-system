#!/bin/bash
# Health check para Streamlit en :8501.
# - Si responde algo != 200, mata y reinicia.
# - Sirve para los hangs silenciosos (proceso vivo, http 500) que vimos.
# - Lo ejecuta launchd cada 5 min.

PROJECT="/Users/lucy/Desktop/Claude Code/felyfit-kol-system"
PYBIN="$PROJECT/.venv/bin/streamlit"
PORT=8501
LOG="$PROJECT/data/healthcheck.log"

mkdir -p "$(dirname "$LOG")"

ts() { date "+%Y-%m-%d %H:%M:%S"; }

code=$(curl -s -o /dev/null -m 10 -w "%{http_code}" "http://localhost:$PORT/" 2>/dev/null)

if [ "$code" = "200" ]; then
  # Healthy — solo log corto cada hora para no llenar el log
  if [ "$(date +%M)" = "00" ]; then
    echo "[$(ts)] OK 200" >> "$LOG"
  fi
  exit 0
fi

echo "[$(ts)] UNHEALTHY (http=$code) — restarting Streamlit" >> "$LOG"

# Mata cualquier streamlit que esté vivo
pkill -f "streamlit run app.py" 2>/dev/null
sleep 2

# Si quedó algo escuchando el puerto, mata con saña
lsof -ti tcp:$PORT 2>/dev/null | xargs kill -9 2>/dev/null
sleep 1

# Reinicia
cd "$PROJECT"
nohup "$PYBIN" run app.py --server.port $PORT > /tmp/streamlit.log 2>&1 &
disown

# Verifica con timeout 30s
for i in $(seq 1 30); do
  sleep 1
  c=$(curl -s -o /dev/null -m 3 -w "%{http_code}" "http://localhost:$PORT/" 2>/dev/null)
  if [ "$c" = "200" ]; then
    echo "[$(ts)] Restarted OK after ${i}s" >> "$LOG"
    exit 0
  fi
done

echo "[$(ts)] FAILED to restart after 30s" >> "$LOG"
exit 1
