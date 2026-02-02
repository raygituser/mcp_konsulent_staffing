@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0traffic_generator.ps1" %*
