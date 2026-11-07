@echo off
cd /d "%~dp0.."
python -m backend.workbench_server --open
pause
