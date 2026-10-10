@echo off
setlocal
title VISION - Automatic processing
call "%~dp0Start VISION.cmd" -BackgroundControls %*
if errorlevel 1 (
  echo.
  echo The controls could not open. Your work and account files were kept.
  echo If Windows blocked this starter, stop and ask the project maintainer for help.
  echo Do not change security settings.
  pause
  exit /b 1
)
exit /b 0
