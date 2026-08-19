@echo off
setlocal
title Installation de DubPack Creator
cd /d "%~dp0"

echo.
echo   ==============================================
echo    DubPack Creator - Installation
echo   ==============================================
echo.
echo   Cette etape se fait une seule fois.
echo   Elle installe Python, ffmpeg et le moteur de
echo   transcription dans ce dossier. Compte 5 a 15 min
echo   selon ta connexion.
echo.
pause

REM ---------- Recherche de Python ----------
set "PY_CMD="
py -3 --version >nul 2>nul && set "PY_CMD=py -3"
if not defined PY_CMD (
    python --version >nul 2>nul && set "PY_CMD=python"
)

if not defined PY_CMD (
    echo.
    echo   Python n'est pas installe sur ce PC.
    echo.
    echo   1. La page de telechargement va s'ouvrir.
    echo   2. Telecharge "Windows installer (64-bit)".
    echo   3. IMPORTANT : coche "Add python.exe to PATH"
    echo      en bas de la premiere fenetre d'installation.
    echo   4. Termine l'installation, puis relance INSTALLER.bat.
    echo.
    pause
    start "" "https://www.python.org/downloads/windows/"
    exit /b 1
)

echo.
echo   Python detecte : %PY_CMD%
%PY_CMD% "tools\install.py" %*
set "CODE=%ERRORLEVEL%"

echo.
if "%CODE%"=="0" (
    echo   Tout est pret. Tu peux fermer cette fenetre
    echo   et lancer DEMARRER.bat ^(ou le raccourci sur le Bureau^).
) else (
    echo   L'installation s'est terminee avec des erreurs.
    echo   Lis les messages ci-dessus : ils indiquent quoi faire.
)
echo.
pause
exit /b %CODE%
