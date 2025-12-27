#!/usr/bin/env python3
"""
Enhanced Proxy Routes with FakeTLS Support for HoseinProxy Panel
This module adds complete FakeTLS functionality to the existing panel
"""

import secrets
import docker
import time
import subprocess
import json
import os
from datetime import datetime, timedelta
from flask import Blueprint, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required
from app.models import Proxy
from app.extensions import db
from app.utils.helpers import (
    log_activity,
    normalize_tls_domain,
    parse_mtproxy_secret_input,
)
from app.services.docker_client import client as docker_client

# Popular domains for FakeTLS
POPULAR_DOMAINS = [
    {"value": "google.com", "name": "Google (پیشنهادی)", "description": "بیشترین اعتبار و پایداری"},
    {"value": "cloudflare.com", "name": "Cloudflare", "description": "مناسب برای محیط‌های فنی"},
    {"value": "microsoft.com", "name": "Microsoft", "description": "مناسب برای شبکه‌های سازمانی"},
    {"value": "apple.com", "name": "Apple", "description": "مناسب برای کاربران iOS/macOS"},
    {"value": "amazon.com", "name": "Amazon", "description": "ترافیک تجارت الکترونیک"},
    {"value": "facebook.com", "name": "Facebook", "description": "ترافیک شبکه‌های اجتماعی"},
    {"value": "twitter.com", "name": "Twitter", "description": "ترافیک شبکه‌های اجتماعی"},
    {"value": "instagram.com", "name": "Instagram", "description": "ترافیک شبکه‌های اجتماعی"},
    {"value": "whatsapp.com", "name": "WhatsApp", "description": "ترافیک پیام‌رسان"},
    {"value": "telegram.org", "name": "Telegram", "description": "ترافیک پیام‌رسان"},
    {"value": "cdn.discordapp.com", "name": "Discord CDN", "description": "بازی/ارتباطات"},
    {"value": "cdn.cloudflare.com", "name": "Cloudflare CDN", "description": "ترافیک CDN"},
    {"value": "ajax.googleapis.com", "name": "Google AJAX", "description": "APIهای Google"},
    {"value": "fonts.googleapis.com", "name": "Google Fonts", "description": "فونت‌های وب"},
    {"value": "apis.google.com", "name": "Google APIs", "description": "APIهای Google"},
    {"value": "ssl.gstatic.com", "name": "Google Static", "description": "محتوای استاتیک Google"},
    {"value": "www.gstatic.com", "name": "Google Static", "description": "محتوای استاتیک Google"},
    {"value": "accounts.google.com", "name": "Google Accounts", "description": "احراز هویت Google"},
    {"value": "drive.google.com", "name": "Google Drive", "description": "Google Drive"},
    {"value": "docs.google.com", "name": "Google Docs", "description": "Google Docs"}
]

def create_faketls_dockerfile(project_dir):
    """Create Dockerfile for FakeTLS proxy"""
    dockerfile_content = '''FROM golang:1.21-alpine AS builder

RUN apk add --no-cache git openssl

WORKDIR /app

# Clone MTProxy source
RUN git clone https://github.com/TelegramMessenger/MTProxy.git . && \
    go mod init mtproxy || true && \
    go mod tidy || true

# Build the proxy with FakeTLS support
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o mtproto-proxy ./cmd/proxy

FROM alpine:latest

RUN apk --no-cache add ca-certificates openssl

WORKDIR /root/

COPY --from=builder /app/mtproto-proxy .

# Create directories
RUN mkdir -p /var/log/mtproto /etc/ssl/certs /etc/ssl/private

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 443

ENTRYPOINT ["/entrypoint.sh"]
'''
    
    dockerfile_path = os.path.join(project_dir, 'Dockerfile')
    with open(dockerfile_path, 'w') as f:
        f.write(dockerfile_content)
    
    return dockerfile_path

def create_faketls_entrypoint(project_dir, port, secret, domain, workers, tag):
    """Create entrypoint script for FakeTLS proxy"""
    # Generate FakeTLS secret
    domain_hex = domain.encode('utf-8').hex()
    fake_secret = f"ee{secret}{domain_hex}"
    
    entrypoint_content = f'''#!/bin/sh
set -e

# Configuration
SECRET="{secret}"
WORKERS="{workers}"
TAG="{tag}"
TLS_DOMAIN="{domain}"
PORT="{port}"
FAKE_SECRET="{fake_secret}"

echo "==========================================="
echo "🏗️  MTProto FakeTLS Proxy Starting"
echo "==========================================="
echo "📡 Domain: $TLS_DOMAIN"
echo "🔌 Port: $PORT"
echo "👷 Workers: $WORKERS"
echo "🔑 Fake Secret: $FAKE_SECRET"
echo "==========================================="

# Generate certificate for fake domain
echo "🔐 Generating TLS certificate for $TLS_DOMAIN..."
mkdir -p /etc/ssl/certs /etc/ssl/private

# Generate private key
openssl genrsa -out /etc/ssl/private/privkey.pem 2048

# Generate certificate signing request
openssl req -new -key /etc/ssl/private/privkey.pem -out /tmp/cert.csr \
    -subj "/C=US/ST=CA/L=Mountain View/O=Google LLC/CN=$TLS_DOMAIN"

# Generate self-signed certificate
openssl x509 -req -days 3650 -in /tmp/cert.csr -signkey /etc/ssl/private/privkey.pem \
    -out /etc/ssl/certs/fullchain.pem

# Clean up
rm -f /tmp/cert.csr

# Prepare tag parameter
TAG_PARAM=""
if [ -n "$TAG" ]; then
    TAG_PARAM="--tag $TAG"
fi

echo "🚀 Starting MTProto proxy with FakeTLS..."
echo "📊 Logs will be available in /var/log/mtproto/"

# Create log directory
mkdir -p /var/log/mtproto

# Start the proxy with FakeTLS support
exec ./mtproto-proxy \\
    -u nobody \\
    -p 8888,80,$PORT \\
    -H $PORT \\
    -S $FAKE_SECRET \\
    --address 0.0.0.0 \\
    --port $PORT \\
    --http-ports 80 \\
    --slaves $WORKERS \\
    --max-special-connections 60000 \\
    --allow-skip-dh \\
    --cert /etc/ssl/certs/fullchain.pem \\
    --key /etc/ssl/private/privkey.pem \\
    --dc 1,149.154.175.50,443 \\
    --dc 2,149.154.167.51,443 \\
    --dc 3,149.154.175.100,443 \\
    --dc 4,149.154.167.91,443 \\
    --dc 5,91.108.56.151,443 \\
    $TAG_PARAM \\
    2>&1 | tee /var/log/mtproto/proxy.log
'''
    
    entrypoint_path = os.path.join(project_dir, 'entrypoint.sh')
    with open(entrypoint_path, 'w') as f:
        f.write(entrypoint_content)
    
    # Make it executable
    os.chmod(entrypoint_path, 0o755)
    
    return entrypoint_path

def create_faketls_docker_compose(project_dir, port, secret, domain, workers, tag):
    """Create Docker Compose configuration for FakeTLS proxy"""
    compose_content = f'''version: '3.8'

services:
  mtproto-faketls-{port}:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: mtproto_faketls_{port}
    restart: always
    ports:
      - "{port}:443"
    environment:
      - SECRET={secret}
      - TAG={tag or ''}
      - WORKERS={workers}
      - TLS_DOMAIN={domain}
      - PORT={port}
    volumes:
      - ./logs:/var/log/mtproto
    networks:
      - mtproto_network
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

networks:
  mtproto_network:
    driver: bridge
'''
    
    compose_path = os.path.join(project_dir, 'docker-compose.yml')
    with open(compose_path, 'w') as f:
        f.write(compose_content)
    
    return compose_path

def start_faketls_proxy(port, secret, domain, workers, tag, name, quota_bytes, expiry_date, proxy_ip):
    """Start a FakeTLS proxy using Docker"""
    try:
        # Create project directory
        project_dir = f"/opt/mtproto-faketls-{port}"
        os.makedirs(project_dir, exist_ok=True)
        
        # Create Docker files
        dockerfile_path = create_faketls_dockerfile(project_dir)
        entrypoint_path = create_faketls_entrypoint(project_dir, port, secret, domain, workers, tag)
        compose_path = create_faketls_docker_compose(project_dir, port, secret, domain, workers, tag)
        
        # Build and start the container
        cmd = ['docker-compose', '-f', compose_path, 'up', '-d', '--build']
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
        
        if result.returncode != 0:
            raise Exception(f"Docker Compose failed: {result.stderr}")
        
        # Wait for container to start
        time.sleep(5)
        
        # Get container ID
        cmd = ['docker-compose', '-f', compose_path, 'ps', '-q']
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
        container_id = result.stdout.strip()
        
        if not container_id:
            raise Exception("Container not found after startup")
        
        return container_id
        
    except Exception as e:
        # Cleanup on failure
        try:
            if os.path.exists(project_dir):
                import shutil
                shutil.rmtree(project_dir)
        except:
            pass
        raise e

def get_faketls_proxy_logs(port, lines=50):
    """Get logs for a FakeTLS proxy"""
    try:
        project_dir = f"/opt/mtproto-faketls-{port}"
        compose_path = os.path.join(project_dir, 'docker-compose.yml')
        
        if os.path.exists(compose_path):
            cmd = ['docker-compose', '-f', compose_path, 'logs', '--tail', str(lines)]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
            
            if result.returncode == 0:
                return result.stdout
            else:
                return f"Error getting logs: {result.stderr}"
        else:
            return "Docker Compose file not found"
    
    except Exception as e:
        return f"Error getting logs: {str(e)}"

def stop_faketls_proxy(port):
    """Stop a FakeTLS proxy"""
    try:
        project_dir = f"/opt/mtproto-faketls-{port}"
        compose_path = os.path.join(project_dir, 'docker-compose.yml')
        
        if os.path.exists(compose_path):
            cmd = ['docker-compose', '-f', compose_path, 'down']
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
            return result.returncode == 0
        return False
    except:
        return False

def restart_faketls_proxy(port):
    """Restart a FakeTLS proxy"""
    try:
        project_dir = f"/opt/mtproto-faketls-{port}"
        compose_path = os.path.join(project_dir, 'docker-compose.yml')
        
        if os.path.exists(compose_path):
            cmd = ['docker-compose', '-f', compose_path, 'restart']
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
            return result.returncode == 0
        return False
    except:
        return False

def get_server_ip():
    """Get server public IP"""
    try:
        # Try multiple IP detection services
        services = [
            'curl -s ifconfig.me',
            'curl -s ipinfo.io/ip',
            'curl -s api.ipify.org',
            'curl -s checkip.amazonaws.com'
        ]
        
        for service in services:
            try:
                result = subprocess.run(service.split(), capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    ip = result.stdout.strip()
                    # Validate IP format
                    import ipaddress
                    ipaddress.ip_address(ip)
                    return ip
            except:
                continue
        
        return "YOUR_SERVER_IP"
    except:
        return "YOUR_SERVER_IP"

def generate_faketls_proxy_link(port, secret, domain):
    """Generate Telegram proxy link for FakeTLS"""
    domain_hex = domain.encode('utf-8').hex()
    fake_secret = f"ee{secret}{domain_hex}"
    server_ip = get_server_ip()
    
    return {
        'telegram': f"https://t.me/proxy?server={server_ip}&port={port}&secret={fake_secret}",
        'direct': f"tg://proxy?server={server_ip}&port={port}&secret={fake_secret}",
        'server_ip': server_ip,
        'port': port,
        'secret': fake_secret,
        'domain': domain
    }