@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0Launch-Core-Free.ps1"
exit /b %errorlevel%
