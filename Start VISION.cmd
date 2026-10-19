@echo off
setlocal
title VISION Community
if not defined LOCALAPPDATA (
  echo VISION could not find your private application folder.
  pause
  exit /b 1
)
set "VISION_ROOT=%LOCALAPPDATA%\vision-community\desktop"
if not exist "%VISION_ROOT%" mkdir "%VISION_ROOT%"
set "VISION_LOG=%VISION_ROOT%\launcher-console-%RANDOM%-%RANDOM%.log"
set "VISION_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "VISION_POWERSHELL=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
"%VISION_POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\Start-Vision.ps1" %* 2>"%VISION_LOG%"
set "VISION_EXIT=%errorlevel%"
if not "%VISION_EXIT%"=="0" (
  echo.
  echo VISION could not start. Your files and diagnostic information were kept.
  type "%VISION_LOG%"
  echo Diagnostic folder: %VISION_ROOT%
  echo If your organization blocked this starter, ask its administrator or the project maintainer for help.
  pause
)
exit /b %VISION_EXIT%
