@echo off
rem WATTLY - avvio rapido (Windows)
rem Prepara l'ambiente (virtualenv + dipendenze) e avvia l'applicazione.
setlocal
cd /d "%~dp0"

rem --- 1. ambiente virtuale ------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo >>> Creazione ambiente virtuale (.venv)...
    py -3 -m venv .venv 2>nul
    if errorlevel 1 python -m venv .venv
    if errorlevel 1 (
        echo ERRORE: impossibile creare il virtualenv.
        echo Installa Python da https://www.python.org/ spuntando "Add python.exe to PATH".
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

rem --- 2. dipendenze -------------------------------------------------------
echo >>> Installazione/aggiornamento dipendenze...
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
if errorlevel 1 (
    echo ERRORE durante l'installazione dei pacchetti.
    pause
    exit /b 1
)

rem --- 3. avvio ------------------------------------------------------------
echo >>> Avvio di Wattly...
python -m wattly %*
if errorlevel 1 pause
endlocal
