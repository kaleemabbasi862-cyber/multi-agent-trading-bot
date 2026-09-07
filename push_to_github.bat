@echo off
setlocal
echo ================================================================
echo          Push Repository to GitHub for Render Deployment
echo ================================================================
echo.
set /p REPO_URL="Enter your GitHub Repository URL (e.g., https://github.com/username/trade-talk.git): "

if "%REPO_URL%"=="" (
    echo [!] No URL provided. Aborted.
    pause
    exit /b
)

echo.
echo [*] Adding remote origin...
git remote remove origin >nul 2>nul
git remote add origin %REPO_URL%

echo [*] Pushing main branch to GitHub...
git push -u origin main
git push origin main:master

if %errorlevel% equ 0 (
    echo.
    echo ================================================================
    echo [+] Successfully pushed to GitHub!
    echo [*] Triggering Render Instant Auto-Deploy Hook...
    curl -X POST "https://api.render.com/deploy/srv-daam4fm7bikc738tlmfg?key=0yLqUHNtjAg"
    echo.
    echo [+] Deploy Hook Triggered! Render is building latest commit now.
    echo ================================================================
) else (
    echo.
    echo [!] Push failed. Please check your repository URL or GitHub permissions.
)
echo.
pause
