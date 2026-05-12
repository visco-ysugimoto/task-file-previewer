@echo off
setlocal

cd /d "%~dp0"
echo Registering TaskFilePreviewer context menu including .zip...
if exist "%~dp0TaskFilePreviewer.exe" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_task_file_previewer_context_menu.ps1" -AppPath "%~dp0TaskFilePreviewer.exe" -IncludeZip
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_task_file_previewer_context_menu.ps1" -IncludeZip
)
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Registration failed. Please check the message above.
) else (
    echo.
    echo Registration completed successfully.
)

echo.
pause
exit /b %EXIT_CODE%
