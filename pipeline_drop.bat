@echo off
title SUPER PROTOCOL by Hayakaz3 - Autonomous Live Wallpaper Studio
cd /d "%~dp0"

if "%~1"=="" (
    echo.
    echo  [ERROR] No video stream detected!
    echo  Please drag and drop your replacement MP4 video onto this BAT script.
    echo.
    pause
    exit /b
)

python studio.py "%~1"
pause