#!/usr/bin/env bash
# WATTLY — avvio rapido (Linux/macOS)
# Prepara l'ambiente (virtualenv + dipendenze) e avvia l'applicazione.
set -e

cd "$(dirname "$0")"

# --- 1. ambiente virtuale -------------------------------------------------
if [ ! -d ".venv" ]; then
    echo ">>> Creazione ambiente virtuale (.venv)..."
    if ! python3 -m venv .venv; then
        echo "ERRORE: impossibile creare il virtualenv."
        echo "Su Debian/Ubuntu installa prima: sudo apt install python3-venv python3-pip"
        exit 1
    fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# --- 2. dipendenze --------------------------------------------------------
echo ">>> Installazione/aggiornamento dipendenze..."
python -m pip install -q --upgrade pip
if ! pip install -q -r requirements.txt; then
    echo "ERRORE durante l'installazione dei pacchetti."
    exit 1
fi

# --- 3. avvio -------------------------------------------------------------
echo ">>> Avvio di Wattly..."
echo "    (se la finestra desktop non si apre, l'app resta disponibile su http://127.0.0.1:5055)"
exec python -m wattly "$@"
