@echo off
REM MTProto FakeTLS Setup Script for Windows
REM This script sets up FakeTLS with popular domains like google.com, cloudflare.com, etc.

echo [INFO] Setting up MTProto FakeTLS proxy configuration...
echo.

REM Popular domains for FakeTLS
echo Available domains for FakeTLS:
echo.
echo 1. google.com	echo 2. cloudflare.com	echo 3. microsoft.com	echo 4. apple.com	echo 5. amazon.com
echo 6. facebook.com	echo 7. twitter.com	echo 8. instagram.com	echo 9. whatsapp.com	echo 10. telegram.org
echo 11. cdn.discordapp.com	echo 12. cdn.cloudflare.com	echo 13. ajax.googleapis.com	echo 14. fonts.googleapis.com	echo 15. apis.google.com
echo 16. ssl.gstatic.com	echo 17. www.gstatic.com	echo 18. accounts.google.com	echo 19. drive.google.com	echo 20. docs.google.com
echo.

REM Get user input
set /p DOMAIN_NUM="Select domain number (1-20): "
set /p PORT="Enter port number: "
set /p WORKERS="Enter number of workers (default: 4): "
set /p TAG="Enter proxy tag (optional): "
set /p NAME="Enter proxy name (optional): "

REM Validate domain selection
if "%DOMAIN_NUM%"=="1" set DOMAIN=google.com
if "%DOMAIN_NUM%"=="2" set DOMAIN=cloudflare.com
if "%DOMAIN_NUM%"=="3" set DOMAIN=microsoft.com
if "%DOMAIN_NUM%"=="4" set DOMAIN=apple.com
if "%DOMAIN_NUM%"=="5" set DOMAIN=amazon.com
if "%DOMAIN_NUM%"=="6" set DOMAIN=facebook.com
if "%DOMAIN_NUM%"=="7" set DOMAIN=twitter.com
if "%DOMAIN_NUM%"=="8" set DOMAIN=instagram.com
if "%DOMAIN_NUM%"=="9" set DOMAIN=whatsapp.com
if "%DOMAIN_NUM%"=="10" set DOMAIN=telegram.org
if "%DOMAIN_NUM%"=="11" set DOMAIN=cdn.discordapp.com
if "%DOMAIN_NUM%"=="12" set DOMAIN=cdn.cloudflare.com
if "%DOMAIN_NUM%"=="13" set DOMAIN=ajax.googleapis.com
if "%DOMAIN_NUM%"=="14" set DOMAIN=fonts.googleapis.com
if "%DOMAIN_NUM%"=="15" set DOMAIN=apis.google.com
if "%DOMAIN_NUM%"=="16" set DOMAIN=ssl.gstatic.com
if "%DOMAIN_NUM%"=="17" set DOMAIN=www.gstatic.com
if "%DOMAIN_NUM%"=="18" set DOMAIN=accounts.google.com
if "%DOMAIN_NUM%"=="19" set DOMAIN=drive.google.com
if "%DOMAIN_NUM%"=="20" set DOMAIN=docs.google.com

if "%DOMAIN%"=="" (
    echo [ERROR] Invalid domain selection
    exit /b 1
)

if "%WORKERS%"=="" set WORKERS=4

REM Generate random secret
echo [INFO] Generating random secret...
for /f "tokens=1" %%i in ('powershell -Command "-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | %%{[char]$_})"') do set SECRET=%%i

echo [INFO] Setting up FakeTLS proxy with domain: %DOMAIN%
echo [INFO] Port: %PORT%
echo [INFO] Workers: %WORKERS%
echo [INFO] Secret: %SECRET%

REM Create necessary directories
if not exist ssl mkdir ssl
if not exist logs mkdir logs

REM Create Docker Compose file for FakeTLS
echo version: '3.8' > docker-compose-faketls.yml
echo. >> docker-compose-faketls.yml
echo services: >> docker-compose-faketls.yml
echo   mtproto-faketls-%PORT%: >> docker-compose-faketls.yml
echo     build: >> docker-compose-faketls.yml
echo       context: . >> docker-compose-faketls.yml
echo       dockerfile: Dockerfile.faketls >> docker-compose-faketls.yml
echo     container_name: mtproto_faketls_%PORT% >> docker-compose-faketls.yml
echo     restart: always >> docker-compose-faketls.yml
echo     ports: >> docker-compose-faketls.yml
echo       - "%PORT%:443" >> docker-compose-faketls.yml
echo     environment: >> docker-compose-faketls.yml
echo       SECRET: %SECRET% >> docker-compose-faketls.yml
echo       TAG: %TAG% >> docker-compose-faketls.yml
echo       WORKERS: %WORKERS% >> docker-compose-faketls.yml
echo       TLS_DOMAIN: %DOMAIN% >> docker-compose-faketls.yml
echo       PORT: 443 >> docker-compose-faketls.yml
echo     volumes: >> docker-compose-faketls.yml
echo       - ./ssl:/etc/ssl/certs:ro >> docker-compose-faketls.yml
echo       - ./logs:/var/log/mtproto >> docker-compose-faketls.yml
echo     networks: >> docker-compose-faketls.yml
echo       - mtproto_network >> docker-compose-faketls.yml
echo. >> docker-compose-faketls.yml
echo networks: >> docker-compose-faketls.yml
echo   mtproto_network: >> docker-compose-faketls.yml
echo     driver: bridge >> docker-compose-faketls.yml

REM Create Dockerfile for FakeTLS
echo FROM golang:1.21-alpine AS builder > Dockerfile.faketls
echo. >> Dockerfile.faketls
echo RUN apk add --no-cache git openssl >> Dockerfile.faketls
echo. >> Dockerfile.faketls
echo WORKDIR /app >> Dockerfile.faketls
echo. >> Dockerfile.faketls
echo # Clone MTProxy source >> Dockerfile.faketls
echo RUN git clone https://github.com/TelegramMessenger/MTProxy.git . ^&^& \ >> Dockerfile.faketls
echo     go mod init mtproxy ^|^| true ^&^& \ >> Dockerfile.faketls
echo     go mod tidy ^|^| true >> Dockerfile.faketls
echo. >> Dockerfile.faketls
echo # Build the proxy >> Dockerfile.faketls
echo RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o mtproto-proxy ./cmd/proxy >> Dockerfile.faketls
echo. >> Dockerfile.faketls
echo FROM alpine:latest >> Dockerfile.faketls
echo. >> Dockerfile.faketls
echo RUN apk --no-cache add ca-certificates openssl >> Dockerfile.faketls
echo. >> Dockerfile.faketls
echo WORKDIR /root/ >> Dockerfile.faketls
echo. >> Dockerfile.faketls
echo COPY --from=builder /app/mtproto-proxy . >> Dockerfile.faketls
echo. >> Dockerfile.faketls
echo # Create directories >> Dockerfile.faketls
echo RUN mkdir -p /var/log/mtproto /etc/ssl/certs /etc/ssl/private >> Dockerfile.faketls
echo. >> Dockerfile.faketls
echo # Copy entrypoint script >> Dockerfile.faketls
echo COPY entrypoint-faketls.sh /entrypoint.sh >> Dockerfile.faketls
echo RUN chmod +x /entrypoint.sh >> Dockerfile.faketls
echo. >> Dockerfile.faketls
echo EXPOSE 443 >> Dockerfile.faketls
echo. >> Dockerfile.faketls
echo ENTRYPOINT ["/entrypoint.sh"] >> Dockerfile.faketls

REM Create entrypoint script
echo #!/bin/sh > entrypoint-faketls.sh
echo set -e >> entrypoint-faketls.sh
echo. >> entrypoint-faketls.sh
echo SECRET=${SECRET:-$(openssl rand -hex 16)} >> entrypoint-faketls.sh
echo WORKERS=${WORKERS:-4} >> entrypoint-faketls.sh
echo TAG=${TAG:-} >> entrypoint-faketls.sh
echo TLS_DOMAIN=${TLS_DOMAIN:-google.com} >> entrypoint-faketls.sh
echo PORT=${PORT:-443} >> entrypoint-faketls.sh
echo. >> entrypoint-faketls.sh
echo echo "Setting up FakeTLS proxy..." >> entrypoint-faketls.sh
echo echo "Domain: $TLS_DOMAIN" >> entrypoint-faketls.sh
echo echo "Port: $PORT" >> entrypoint-faketls.sh
echo echo "Workers: $WORKERS" >> entrypoint-faketls.sh
echo. >> entrypoint-faketls.sh
echo # Generate certificate for fake domain >> entrypoint-faketls.sh
echo mkdir -p /etc/ssl/certs /etc/ssl/private >> entrypoint-faketls.sh
echo. >> entrypoint-faketls.sh
echo # Generate private key >> entrypoint-faketls.sh
echo openssl genrsa -out /etc/ssl/private/privkey.pem 2048 >> entrypoint-faketls.sh
echo. >> entrypoint-faketls.sh
echo # Generate certificate signing request >> entrypoint-faketls.sh
echo openssl req -new -key /etc/ssl/private/privkey.pem -out /tmp/cert.csr \ >> entrypoint-faketls.sh
echo     -subj "/C=US/ST=CA/L=Mountain View/O=Google LLC/CN=$TLS_DOMAIN" >> entrypoint-faketls.sh
echo. >> entrypoint-faketls.sh
echo # Generate self-signed certificate >> entrypoint-faketls.sh
echo openssl x509 -req -days 3650 -in /tmp/cert.csr -signkey /etc/ssl/private/privkey.pem \ >> entrypoint-faketls.sh
echo     -out /etc/ssl/certs/fullchain.pem >> entrypoint-faketls.sh
echo. >> entrypoint-faketls.sh
echo # Clean up >> entrypoint-faketls.sh
echo rm -f /tmp/cert.csr >> entrypoint-faketls.sh
echo. >> entrypoint-faketls.sh
echo # Prepare FakeTLS secret >> entrypoint-faketls.sh
echo echo "Preparing FakeTLS secret for domain: $TLS_DOMAIN" >> entrypoint-faketls.sh
echo DOMAIN_HEX=$(echo -n "$TLS_DOMAIN" | hexdump -v -e '1/1 "%02x"') >> entrypoint-faketls.sh
echo FAKE_SECRET="ee${SECRET}${DOMAIN_HEX}" >> entrypoint-faketls.sh
echo. >> entrypoint-faketls.sh
echo echo "Fake Secret: $FAKE_SECRET" >> entrypoint-faketls.sh
echo. >> entrypoint-faketls.sh
echo TAG_PARAM="" >> entrypoint-faketls.sh
echo if [ -n "$TAG" ]; then >> entrypoint-faketls.sh
echo     TAG_PARAM="--tag $TAG" >> entrypoint-faketls.sh
echo fi >> entrypoint-faketls.sh
echo. >> entrypoint-faketls.sh
echo # Start the proxy >> entrypoint-faketls.sh
echo exec ./mtproto-proxy \ >> entrypoint-faketls.sh
echo     -u nobody \ >> entrypoint-faketls.sh
echo     -p 8888,80,$PORT \ >> entrypoint-faketls.sh
echo     -H $PORT \ >> entrypoint-faketls.sh
echo     -S $FAKE_SECRET \ >> entrypoint-faketls.sh
echo     --address 0.0.0.0 \ >> entrypoint-faketls.sh
echo     --port $PORT \ >> entrypoint-faketls.sh
echo     --http-ports 80 \ >> entrypoint-faketls.sh
echo     --slaves $WORKERS \ >> entrypoint-faketls.sh
echo     --max-special-connections 60000 \ >> entrypoint-faketls.sh
echo     --allow-skip-dh \ >> entrypoint-faketls.sh
echo     --cert /etc/ssl/certs/fullchain.pem \ >> entrypoint-faketls.sh
echo     --key /etc/ssl/private/privkey.pem \ >> entrypoint-faketls.sh
echo     --dc 1,149.154.175.50,443 \ >> entrypoint-faketls.sh
echo     --dc 2,149.154.167.51,443 \ >> entrypoint-faketls.sh
echo     --dc 3,149.154.175.100,443 \ >> entrypoint-faketls.sh
echo     --dc 4,149.154.167.91,443 \ >> entrypoint-faketls.sh
echo     --dc 5,91.108.56.151,443 \ >> entrypoint-faketls.sh
echo     $TAG_PARAM >> entrypoint-faketls.sh

REM Generate FakeTLS secret
powershell -Command "$domainHex = [System.BitConverter]::ToString([System.Text.Encoding]::UTF8.GetBytes('%DOMAIN%')).Replace('-', '').ToLower(); echo 'ee%SECRET%$domainHex'" > faketls_secret.txt
set /p FAKE_SECRET=<faketls_secret.txt

REM Create proxy info file
echo MTProto FakeTLS Proxy Information > proxy-faketls-info.txt
echo ============================== >> proxy-faketls-info.txt
echo Domain: %DOMAIN% >> proxy-faketls-info.txt
echo Secret: %SECRET% >> proxy-faketls-info.txt
echo Fake Secret: %FAKE_SECRET% >> proxy-faketls-info.txt
echo Workers: %WORKERS% >> proxy-faketls-info.txt
echo Tag: %TAG% >> proxy-faketls-info.txt
echo Port: %PORT% >> proxy-faketls-info.txt
echo. >> proxy-faketls-info.txt
echo Proxy Link: https://t.me/proxy?server=SERVER_IP^&port=%PORT%^&secret=%FAKE_SECRET% >> proxy-faketls-info.txt
echo. >> proxy-faketls-info.txt
echo Docker Commands: >> proxy-faketls-info.txt
echo - Start: docker-compose -f docker-compose-faketls.yml up -d >> proxy-faketls-info.txt
echo - View logs: docker-compose -f docker-compose-faketls.yml logs -f >> proxy-faketls-info.txt
echo - Stop: docker-compose -f docker-compose-faketls.yml down >> proxy-faketls-info.txt
echo - Restart: docker-compose -f docker-compose-faketls.yml restart >> proxy-faketls-info.txt

echo [INFO] Building and starting FakeTLS proxy...
docker-compose -f docker-compose-faketls.yml up -d

echo [INFO] FakeTLS proxy setup completed!
echo [INFO] Domain: %DOMAIN%
echo [INFO] Port: %PORT%
echo [INFO] Secret: %SECRET%
echo [INFO] Fake Secret: %FAKE_SECRET%
echo.
echo Proxy information saved to: proxy-faketls-info.txt
echo.
echo To test the proxy:
echo 1. Open Telegram
echo 2. Go to Settings ^> Data and Storage ^> Proxy Settings
echo 3. Add proxy using the link in proxy-faketls-info.txt
echo.
echo Replace SERVER_IP with your actual server IP address in the proxy link.
pause