@echo off
REM MTProto TLS Setup Script for Windows
REM This script sets up TLS for MTProto proxy with Let's Encrypt certificates

echo [INFO] Setting up MTProto TLS proxy configuration...

REM Get user input
set /p DOMAIN="Enter your domain name (e.g., proxy.yourdomain.com): "
set /p EMAIL="Enter your email for Let's Encrypt: "
set /p SECRET="Enter proxy secret (leave empty to generate): "
set /p WORKERS="Enter number of workers (default: 4): "
set /p TAG="Enter proxy tag (optional): "

REM Set defaults
if "%SECRET%"=="" set SECRET=
if "%WORKERS%"=="" set WORKERS=4

REM Generate random secret if not provided
if "%SECRET%"=="" (
    echo [INFO] Generating random secret...
    for /f "tokens=1" %%i in ('powershell -Command "-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | %%{[char]$_})"') do set SECRET=%%i
)

echo [INFO] Setting up MTProto TLS proxy for domain: %DOMAIN%

REM Create necessary directories
if not exist nginx\ssl mkdir nginx\ssl
if not exist nginx\logs mkdir nginx\logs
if not exist ssl mkdir ssl
if not exist logs mkdir logs

REM Create environment file
echo DOMAIN=%DOMAIN% > .env
echo SECRET=%SECRET% >> .env
echo WORKERS=%WORKERS% >> .env
echo TAG=%TAG% >> .env
echo TLS_DOMAIN=%DOMAIN% >> .env

REM Create initial self-signed certificate for nginx
echo [INFO] Creating initial self-signed certificate...
openssl req -x509 -nodes -days 365 -newkey rsa:2048 ^
    -keyout nginx\ssl\privkey.pem ^
    -out nginx\ssl\fullchain.pem ^
    -subj "/C=US/ST=State/L=City/O=Organization/CN=%DOMAIN%"

REM Update nginx configuration with the domain
powershell -Command "(Get-Content nginx\conf.d\mtproto-tls.conf) -replace 'your-domain.com', '%DOMAIN%' | Set-Content nginx\conf.d\mtproto-tls.conf"

REM Start services in detached mode
echo [INFO] Starting Docker services...
docker-compose up -d

REM Wait for services to start
timeout /t 10 /nobreak > nul

REM Test if nginx is running
curl -f http://localhost/health > nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Nginx is running successfully
) else (
    echo [WARNING] Nginx health check failed, but this might be normal during initial setup
)

REM Create proxy link
echo [INFO] Creating proxy link...
powershell -Command "$domainHex = [System.BitConverter]::ToString([System.Text.Encoding]::UTF8.GetBytes('%DOMAIN%')).Replace('-', '').ToLower(); echo 'https://t.me/proxy?server=%DOMAIN%&port=443&secret=ee%SECRET%$domainHex'" > proxy_link.txt
set /p PROXY_LINK=<proxy_link.txt

REM Save proxy information
echo MTProto TLS Proxy Information > proxy_info.txt
echo ============================== >> proxy_info.txt
echo Domain: %DOMAIN% >> proxy_info.txt
echo Secret: %SECRET% >> proxy_info.txt
echo Workers: %WORKERS% >> proxy_info.txt
echo Tag: %TAG% >> proxy_info.txt
echo Proxy Link: %PROXY_LINK% >> proxy_info.txt
echo ============================== >> proxy_info.txt
echo. >> proxy_info.txt
echo Docker Commands: >> proxy_info.txt
echo - View logs: docker-compose logs -f >> proxy_info.txt
echo - Stop services: docker-compose down >> proxy_info.txt
echo - Restart services: docker-compose restart >> proxy_info.txt
echo - Update certificates: docker-compose exec certbot certbot renew >> proxy_info.txt

echo [INFO] Setup completed successfully!
echo [INFO] Proxy information saved to proxy_info.txt
echo [INFO] Proxy link: %PROXY_LINK%
echo.
echo ==============================
echo MTProto TLS Proxy Information
echo ==============================
echo Domain: %DOMAIN%
echo Secret: %SECRET%
echo Workers: %WORKERS%
echo Tag: %TAG%
echo Proxy Link: %PROXY_LINK%
echo ==============================
echo.
echo To test the proxy:
echo 1. Open Telegram
echo 2. Go to Settings ^> Data and Storage ^> Proxy Settings
echo 3. Add proxy using the link above
echo.
echo For support and updates, check the documentation.
pause