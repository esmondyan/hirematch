@echo off
echo === Killing PID 13204 on port 8000 ===
taskkill /F /PID 13204 2>nul
if %errorlevel% equ 0 (
    echo Process killed successfully.
) else (
    echo Direct taskkill failed, trying via netstat...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
        taskkill /F /PID %%a 2>nul && echo Killed PID %%a || echo Failed to kill PID %%a
    )
)
echo.
echo === Port 8000 status ===
netstat -ano | findstr :8000
if %errorlevel% neq 0 echo Port 8000 is now FREE.
pause
