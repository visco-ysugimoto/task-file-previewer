@echo off
setlocal

cd /d "%~dp0"
echo Unregistering TaskFilePreviewer context menu...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0unregister_task_file_previewer_context_menu.ps1"
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Unregistration failed. Please check the message above.
) else (
    echo.
    echo Unregistration completed successfully.
)

echo.
pause
exit /b %EXIT_CODE%
