@echo off
cd /d "%~dp0"
python run.py
if errorlevel 1 (
    echo.
    echo Erreur lors du lancement. Verifiez que Python et les dependances sont installes :
    echo pip install -r requirements.txt
    pause
)
