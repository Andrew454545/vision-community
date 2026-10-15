@echo off
setlocal
title VISION Local Scenes
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -File "%~dp0windows\Start-LocalScenes.ps1" %*
if errorlevel 1 (
  echo VISION Local Scenes could not start. Keep your files and ask the maintainer for help.
  pause
)
