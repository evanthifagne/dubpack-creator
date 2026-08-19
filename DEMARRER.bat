@echo off
setlocal
title DubPack Creator
cd /d "%~dp0"

REM Environnement installe par INSTALLER.bat
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo.
    echo   DubPack Creator n'est pas encore installe.
    echo   Double-clique d'abord sur INSTALLER.bat
    echo.
    pause
    exit /b 1
)

echo.
echo   Demarrage de DubPack Creator...
echo   Le navigateur va s'ouvrir automatiquement.
echo   GARDE CETTE FENETRE OUVERTE pendant l'utilisation.
echo   Pour arreter : ferme cette fenetre.
echo.

"%VENV_PY%" run.py --skip-install %*
if errorlevel 1 pause
