#!/usr/bin/env bash
set -uo pipefail

# run.sh - Keep-alive do processo do bot com backoff exponencial até 300s
DELAY=2
MAX_DELAY=300

while true; do
  echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Iniciando FarolBot..."
  python3 main.py
  EXIT_CODE=$?
  echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] FarolBot finalizado com código ${EXIT_CODE}."

  # Exit 0: encerramento gracioso
  # Exit 2: erro fatal de configuração ou credenciais (não adianta reiniciar)
  if [ "$EXIT_CODE" -eq 0 ] || [ "$EXIT_CODE" -eq 2 ]; then
    echo "Encerrando run.sh (código ${EXIT_CODE})."
    exit "$EXIT_CODE"
  fi

  echo "Reiniciando em ${DELAY}s (backoff exponencial)..."
  sleep "$DELAY"
  DELAY=$((DELAY * 2))
  if [ "$DELAY" -gt "$MAX_DELAY" ]; then
    DELAY=$MAX_DELAY
  fi
done
