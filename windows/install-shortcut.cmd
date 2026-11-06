@echo off
rem Creates the "kdump-analyzer web UI" icon on the Desktop and in the Start menu.
rem Double-click this file once. Run "python webui\kdump-webui.py --remove-shortcut" to remove the icons.
cd /d "%~dp0.."
where python >nul 2>&1
if %errorlevel%==0 (
    python webui\kdump-webui.py --install-shortcut %*
) else (
    py -3 webui\kdump-webui.py --install-shortcut %*
)
echo.
pause
