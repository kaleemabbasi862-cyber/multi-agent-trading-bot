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

if %errorlevel% equ 0 (
    echo.
    echo ================================================================
    echo [+] Successfully pushed to GitHub!
    echo [+] Now go to Render Dashboard (https://dashboard.render.com):
    echo     1. Click "New +" -> "Blueprint"
    echo     2. Select this repository
    echo     3. Render will automatically read render.yaml and deploy!
    echo ================================================================
) else (
    echo.
    echo [!] Push failed. Please check your repository URL or GitHub permissions.
)
echo.
pause
