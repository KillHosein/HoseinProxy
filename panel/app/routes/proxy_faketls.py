#!/usr/bin/env python3
"""
Enhanced MTProto Proxy Routes with FakeTLS Support
Supports popular domains like google.com, cloudflare.com, etc.
"""

import secrets
import docker
import time
from datetime import datetime, timedelta
from flask import Blueprint, request, redirect, url_for, flash
from flask_login import login_required
from app.models import Proxy
from app.extensions import db
from app.utils.helpers import (
    log_activity,
    normalize_tls_domain,
    parse_mtproxy_secret_input,
)
from app.services.docker_client import client as docker_client

proxy_faketls_bp = Blueprint('proxy_faketls', __name__, url_prefix='/proxy-faketls')

# Popular domains for FakeTLS
POPULAR_DOMAINS = [
    "google.com",
    "cloudflare.com", 
    "microsoft.com",
    "apple.com",
    "amazon.com",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "whatsapp.com",
    "telegram.org",
    "cdn.discordapp.com",
    "cdn.cloudflare.com",
    "ajax.googleapis.com",
    "fonts.googleapis.com",
    "apis.google.com",
    "ssl.gstatic.com",
    "www.gstatic.com",
    "accounts.google.com",
    "drive.google.com",
    "docs.google.com"
]

def _faketls_proxy_image():
    """Return the Docker image for FakeTLS-enabled MTProto proxy"""
    return "mtproto-faketls:latest"

def _build_faketls_proxy_image():
    """Build the FakeTLS proxy Docker image"""
    try:
        # Create Dockerfile content for FakeTLS support
        dockerfile_content = '''FROM golang:1.21-alpine AS builder

RUN apk add --no-cache git openssl

WORKDIR /app

# Clone MTProxy source with FakeTLS support
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
COPY entrypoint-faketls.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 443

ENTRYPOINT ["/entrypoint.sh"]
'''
        
        # Create entrypoint script for FakeTLS
        entrypoint_content = '''#!/bin/sh
set -e

SECRET=${SECRET:-$(openssl rand -hex 16)}
WORKERS=${WORKERS:-4}
TAG=${TAG:-}
TLS_DOMAIN=${TLS_DOMAIN:-google.com}
PORT=${PORT:-443}

# Generate self-signed certificate for the fake domain
echo "Generating certificate for FakeTLS domain: $TLS_DOMAIN"

# Create certificate directory
mkdir -p /etc/ssl/certs /etc/ssl/private

# Generate private key
openssl genrsa -out /etc/ssl/private/privkey.pem 2048

# Generate certificate signing request with fake domain
openssl req -new -key /etc/ssl/private/privkey.pem -out /tmp/cert.csr \
    -subj "/C=US/ST=CA/L=Mountain View/O=Google LLC/CN=$TLS_DOMAIN"

# Generate self-signed certificate
openssl x509 -req -days 3650 -in /tmp/cert.csr -signkey /etc/ssl/private/privkey.pem \
    -out /etc/ssl/certs/fullchain.pem

# Clean up
rm -f /tmp/cert.csr

# Prepare FakeTLS secret
echo "Preparing FakeTLS secret for domain: $TLS_DOMAIN"
DOMAIN_HEX=$(echo -n "$TLS_DOMAIN" | hexdump -v -e '1/1 "%02x"')
FAKE_SECRET="ee${SECRET}${DOMAIN_HEX}"

TAG_PARAM=""
if [ -n "$TAG" ]; then
    TAG_PARAM="--tag $TAG"
fi

echo "Starting FakeTLS proxy..."
echo "Domain: $TLS_DOMAIN"
echo "Port: $PORT"
echo "Workers: $WORKERS"
echo "Fake Secret: $FAKE_SECRET"

# Start the proxy with FakeTLS support
exec ./mtproto-proxy \
    -u nobody \
    -p 8888,80,$PORT \
    -H $PORT \
    -S $FAKE_SECRET \
    --address 0.0.0.0 \
    --port $PORT \
    --http-ports 80 \
    --slaves $WORKERS \
    --max-special-connections 60000 \
    --allow-skip-dh \
    --cert /etc/ssl/certs/fullchain.pem \
    --key /etc/ssl/private/privkey.pem \
    --dc 1,149.154.175.50,443 \
    --dc 2,149.154.167.51,443 \
    --dc 3,149.154.175.100,443 \
    --dc 4,149.154.167.91,443 \
    --dc 5,91.108.56.151,443 \
    $TAG_PARAM
'''
        
        # Write files
        with open('Dockerfile.faketls', 'w') as f:
            f.write(dockerfile_content)
        
        with open('entrypoint-faketls.sh', 'w') as f:
            f.write(entrypoint_content)
        
        # Build the image
        if docker_client:
            docker_client.images.build(
                path='.',
                dockerfile='Dockerfile.faketls',
                tag=_faketls_proxy_image(),
                rm=True
            )
            return True
    except Exception as e:
        print(f"Error building FakeTLS proxy image: {e}")
        return False

@proxy_faketls_bp.route('/add', methods=['POST'])
@login_required
def add_faketls_proxy():
    """Add a new FakeTLS-enabled proxy"""
    port = request.form.get('port', type=int)
    workers = request.form.get('workers', type=int, default=4)
    tag = (request.form.get('tag') or '').strip() or None
    name = (request.form.get('name') or '').strip() or None
    secret = request.form.get('secret')
    tls_domain = request.form.get('tls_domain', 'google.com').strip().lower()
    quota_gb = request.form.get('quota_gb', type=float)
    expiry_days = request.form.get('expiry_days', type=int)
    proxy_ip = (request.form.get('proxy_ip') or '').strip() or None
    
    # Validate domain is in popular domains list
    if tls_domain not in POPULAR_DOMAINS:
        flash(f'دامنه {tls_domain} در لیست دامنه‌های معتبر نیست. از دامنه‌های پیشنهادی استفاده کنید.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    # Calculate quota
    quota_bytes = 0
    if quota_gb is not None and quota_gb > 0:
        quota_bytes = int(quota_gb * 1024 * 1024 * 1024)
    
    # Calculate expiry
    expiry_date = None
    if expiry_days and expiry_days > 0:
        expiry_date = datetime.utcnow() + timedelta(days=expiry_days)
    
    if not secret:
        secret = secrets.token_hex(16)
    
    if not port:
        flash('شماره پورت الزامی است.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if Proxy.query.filter_by(port=port).first():
        flash(f'پورت {port} قبلاً استفاده شده است.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    try:
        # Build FakeTLS proxy image if not exists
        print_status("Building FakeTLS proxy image...")
        if not _build_faketls_proxy_image():
            flash('خطا در ساخت ایمیج FakeTLS proxy.', 'danger')
            return redirect(url_for('main.dashboard'))
        
        # Create Docker container
        ports_config = {'443/tcp': port}
        if proxy_ip:
            ports_config = {'443/tcp': (proxy_ip, port)}
        
        container = docker_client.containers.run(
            _faketls_proxy_image(),
            detach=True,
            ports=ports_config,
            environment={
                'SECRET': secret,
                'TAG': tag or '',
                'WORKERS': workers,
                'TLS_DOMAIN': tls_domain,
                'PORT': 443
            },
            restart_policy={"Name": "always"},
            name=f"mtproto_faketls_{port}"
        )
        
        # Wait for container to start
        time.sleep(3)
        
        # Generate FakeTLS secret
        domain_hex = tls_domain.encode('utf-8').hex()
        fake_secret = f"ee{secret}{domain_hex}"
        
        # Create proxy record in database
        new_proxy = Proxy(
            port=port,
            secret=secret,
            proxy_type="tls",
            tls_domain=tls_domain,
            tag=tag,
            name=name or f"FakeTLS {tls_domain} {port}",
            workers=workers,
            container_id=container.id,
            status="running",
            quota_bytes=quota_bytes,
            quota_start=datetime.utcnow(),
            expiry_date=expiry_date,
            proxy_ip=proxy_ip
        )
        
        db.session.add(new_proxy)
        db.session.commit()
        
        # Generate proxy link
        proxy_link = f"https://t.me/proxy?server={proxy_ip or 'SERVER_IP'}&port={port}&secret={fake_secret}"
        
        log_activity("Create FakeTLS Proxy", f"Created FakeTLS proxy on port {port} for domain {tls_domain}")
        flash(f'پروکسی FakeTLS با دامنه {tls_domain} روی پورت {port} با موفقیت ساخته شد.', 'success')
        flash(f'لینک پروکسی: {proxy_link}', 'info')
        
    except Exception as e:
        flash(f'خطا در ساخت پروکسی FakeTLS: {e}', 'danger')
        log_activity("FakeTLS Proxy Error", str(e))
    
    return redirect(url_for('main.dashboard'))

@proxy_faketls_bp.route('/get-popular-domains', methods=['GET'])
@login_required
def get_popular_domains():
    """Get list of popular domains for FakeTLS"""
    from flask import jsonify
    return jsonify({
        'domains': POPULAR_DOMAINS,
        'success': True
    })

@proxy_faketls_bp.route('/validate-domain', methods=['POST'])
@login_required
def validate_domain():
    """Validate if a domain is suitable for FakeTLS"""
    from flask import jsonify
    domain = request.json.get('domain', '').strip().lower()
    
    is_valid = domain in POPULAR_DOMAINS
    
    return jsonify({
        'valid': is_valid,
        'domain': domain,
        'message': 'Domain is valid for FakeTLS' if is_valid else 'Domain not in popular domains list'
    })