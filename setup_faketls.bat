@echo off
echo 🔧 Setting up Fake TLS Proxy for HoseinProxy Panel

REM Check if Docker is running
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker is not running. Please start Docker first.
    exit /b 1
)

echo 📦 Building Fake TLS Docker image...
cd proxy

REM Build the Docker image
docker build -t mtproxy-faketls:latest .

if %errorlevel% neq 0 (
    echo ❌ Failed to build Docker image
    exit /b 1
)

echo ✅ Fake TLS Docker image built successfully!

REM Test the image
echo 🧪 Testing Fake TLS proxy...
set TEST_CONTAINER=test-faketls-%RANDOM%
docker run -d --rm --name %TEST_CONTAINER% -p 8443:443 -e SECRET=0123456789abcdef0123456789abcdef -e TLS_DOMAIN=google.com -e WORKERS=2 mtproxy-faketls:latest

timeout /t 5 /nobreak >nul

REM Check if container is running
docker ps | findstr %TEST_CONTAINER% >nul
if %errorlevel% equ 0 (
    echo ✅ Test container is running successfully!
    docker stop %TEST_CONTAINER% >nul
) else (
    echo ❌ Test failed - container is not running
    echo 📋 Container logs:
    docker logs %TEST_CONTAINER% 2>&1 | findstr /v "^$" | findstr /v "^[[:space:]]*$"
    docker rm -f %TEST_CONTAINER% >nul 2>&1
    exit /b 1
)

echo ✅ Test completed successfully!
echo.
echo 🎉 HoseinProxy Fake TLS setup completed!
echo.
echo 📋 Usage Instructions:
echo 1. The fake TLS proxy is now ready to use
echo 2. In your panel, select 'Fake TLS (Anti-Filter)' as proxy type
echo 3. Use popular domains like google.com, cloudflare.com for TLS handshake
echo 4. The proxy will automatically obfuscate traffic to bypass filters
echo.
echo 🔧 Available Environment Variables:
echo - SECRET: 32-character hex secret key
echo - TLS_DOMAIN: Domain for fake TLS handshake
echo - TAG: Optional tag for the proxy
echo - WORKERS: Number of worker processes
echo.
echo 🛡️ Anti-Filter Features:
echo - Fake TLS handshake that mimics real HTTPS
echo - Traffic obfuscation to avoid detection
echo - Connection padding with random data
echo - Rate limiting to prevent abuse
echo - Support for popular domains as camouflage
echo.
echo 🔒 Your proxy is now anti-filter ready!

cd ..