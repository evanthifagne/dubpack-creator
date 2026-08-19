@echo off
REM Windows : double-clique ce fichier pour lancer DubPack Creator.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 run.py %*
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python run.py %*
    ) else (
        echo Python 3.10+ est introuvable.
        echo Installe-le depuis https://www.python.org/downloads/ en cochant "Add Python to PATH".
        pause
        exit /b 1
    )
)
if errorlevel 1 pause
