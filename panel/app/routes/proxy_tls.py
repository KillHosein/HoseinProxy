#!/usr/bin/env python3
"""
Enhanced MTProto Proxy Routes with TLS Support
This module adds TLS support to the existing proxy system
"""

import secrets
import docker
import time
import subprocess
import json
from datetime import datetime, timedelta
from flask import Blueprint, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from app.models import Proxy
from app.extensions import db
from app.utils.helpers import (
    log_activity,
    normalize_tls_domain,
    parse_mtproxy_secret_input,
)
from app.services.docker_client import client as docker_client

proxy_tls_bp = Blueprint('proxy_tls', __name__, url_prefix='/proxy-tls')

def _tls_proxy_image():
    """Return the Docker image for TLS-enabled MTProto proxy"""
    return "mtproto-tls:latest"

def _build_tls_proxy_image():
    """Build the TLS proxy Docker image"""
    try:
        # Create Dockerfile content
        dockerfile_content = '''FROM golang:1.21-alpine AS builder

RUN apk add --no-cache git openssl

WORKDIR /app

# Clone MTProxy source
RUN git clone https://github.com/TelegramMessenger/MTProxy.git . && \
    go mod init mtproxy || true && \
    go mod tidy || true

# Build the proxy
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o mtproto-proxy ./cmd/proxy

FROM alpine:latest

RUN apk --no-cache add ca-certificates openssl

WORKDIR /root/

COPY --from=builder /app/mtproto-proxy .

# Create directories
RUN mkdir -p /var/log/mtproto /etc/ssl/certs /etc/ssl/private

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 443

ENTRYPOINT ["/entrypoint.sh"]
'''
        
        # Create entrypoint script
        entrypoint_content = '''#!/bin/sh
set -e

SECRET=${SECRET:-$(openssl rand -hex 16)}
WORKERS=${WORKERS:-4}
TAG=${TAG:-}
TLS_DOMAIN=${TLS_DOMAIN:-}
TLS_CERT_PATH=${TLS_CERT_PATH:-/etc/ssl/certs/fullchain.pem}
TLS_KEY_PATH=${TLS_KEY_PATH:-/etc/ssl/private/privkey.pem}

# Generate certificate if not exists
if [ ! -f "$TLS_CERT_PATH" ] || [ ! -f "$TLS_KEY_PATH" ]; then
    echo "Generating self-signed TLS certificate for domain: $TLS_DOMAIN"
    mkdir -p $(dirname "$TLS_CERT_PATH") $(dirname "$TLS_KEY_PATH")
    openssl genrsa -out "$TLS_KEY_PATH" 2048
    openssl req -new -key "$TLS_KEY_PATH" -out /tmp/cert.csr -subj "/CN=$TLS_DOMAIN"
    openssl x509 -req -days 365 -in /tmp/cert.csr -signkey "$TLS_KEY_PATH" -out "$TLS_CERT_PATH"
    rm -f /tmp/cert.csr
fi

# Prepare TLS secret
if [ -n "$TLS_DOMAIN" ]; then
    DOMAIN_HEX=$(echo -n "$TLS_DOMAIN" | hexdump -v -e '1/1 "%02x"')
    SECRET="ee${SECRET}${DOMAIN_HEX}"
fi

TAG_PARAM=""
if [ -n "$TAG" ]; then
    TAG_PARAM="--tag $TAG"
fi

echo "Starting MTProto TLS proxy..."
echo "Domain: $TLS_DOMAIN"
echo "Workers: $WORKERS"
echo "Secret: $SECRET"

exec ./mtproto-proxy \
    -u nobody \
    -p 8888,80,443 \
    -H 443 \
    -S $SECRET \
    --address 0.0.0.0 \
    --port 443 \
    --http-ports 80 \
    --slaves $WORKERS \
    --max-special-connections 60000 \
    --allow-skip-dh \
    --cert "$TLS_CERT_PATH" \
    --key "$TLS_KEY_PATH" \
    --dc 1,149.154.175.50,443 \
    --dc 2,149.154.167.51,443 \
    --dc 3,149.154.175.100,443 \
    --dc 4,149.154.167.91,443 \
    --dc 5,91.108.56.151,443 \
    $TAG_PARAM
'''
        
        # Write files
        with open('Dockerfile.tls', 'w') as f:
            f.write(dockerfile_content)
        
        with open('entrypoint.sh', 'w') as f:
            f.write(entrypoint_content)
        
        # Build the image
        if docker_client:
            docker_client.images.build(
                path='.',
                dockerfile='Dockerfile.tls',
                tag=_tls_proxy_image(),
                rm=True
            )
            return True
    except Exception as e:
        print(f"Error building TLS proxy image: {e}")
        return False

@proxy_tls_bp.route('/setup', methods=['POST'])
@login_required
def setup_tls_proxy():
    """Setup a new TLS-enabled proxy"""
    domain = request.form.get('domain')
    port = request.form.get('port', type=int)
    workers = request.form.get('workers', type=int, default=4)
    tag = (request.form.get('tag') or '').strip() or None
    name = (request.form.get('name') or '').strip() or None
    secret = request.form.get('secret')
    email = request.form.get('email', f"admin@{domain}")
    
    if not domain:
        flash('دامنه الزامی است.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if not port:
        flash('شماره پورت الزامی است.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Validate domain
    tls_domain = normalize_tls_domain(domain)
    if not tls_domain:
        flash('دامنه نامعتبر است.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if not secret:
        secret = secrets.token_hex(16)
    
    # Check if port is already in use
    if Proxy.query.filter_by(port=port).first():
        flash(f'پورت {port} قبلاً استفاده شده است.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    try:
        # Build TLS proxy image if not exists
        print_status("Building TLS proxy image...")
        if not _build_tls_proxy_image():
            flash('خطا در ساخت ایمیج TLS proxy.', 'danger')
            return redirect(url_for('main.dashboard'))
        
        # Create Docker container
        container = docker_client.containers.run(
            _tls_proxy_image(),
            detach=True,
            ports={'443/tcp': port},
            environment={
                'SECRET': secret,
                'TAG': tag or '',
                'WORKERS': workers,
                'TLS_DOMAIN': tls_domain,
                'TLS_CERT_PATH': '/etc/ssl/certs/fullchain.pem',
                'TLS_KEY_PATH': '/etc/ssl/private/privkey.pem'
            },
            volumes={
                './ssl': {'bind': '/etc/ssl/certs', 'mode': 'ro'},
                './logs': {'bind': '/var/log/mtproto', 'mode': 'rw'}
            },
            restart_policy={"Name": "always"},
            name=f"mtproto_tls_{port}"
        )
        
        # Wait for container to start
        time.sleep(2)
        
        # Create proxy record in database
        new_proxy = Proxy(
            port=port,
            secret=secret,
            proxy_type="tls",
            tls_domain=tls_domain,
            tag=tag,
            name=name or f"TLS Proxy {port}",
            workers=workers,
            container_id=container.id,
            status="running"
        )
        
        db.session.add(new_proxy)
        db.session.commit()
        
        # Generate proxy link
        domain_hex = tls_domain.encode('utf-8').hex()
        proxy_link = f"https://t.me/proxy?server={tls_domain}&port={port}&secret=ee{secret}{domain_hex}"
        
        log_activity("Create TLS Proxy", f"Created TLS proxy on port {port} for domain {tls_domain}")
        flash(f'پروکسی TLS با موفقیت ساخته شد. لینک: {proxy_link}', 'success')
        
    except Exception as e:
        flash(f'خطا در ساخت پروکسی TLS: {e}', 'danger')
        log_activity("TLS Proxy Error", str(e))
    
    return redirect(url_for('main.dashboard'))

@proxy_tls_bp.route('/generate-cert', methods=['POST'])
@login_required
def generate_certificate():
    """Generate Let's Encrypt certificate for TLS proxy"""
    proxy_id = request.form.get('proxy_id', type=int)
    domain = request.form.get('domain')
    email = request.form.get('email', 'admin@localhost')
    
    if not proxy_id or not domain:
        return jsonify({'success': False, 'message': 'Proxy ID and domain are required'})
    
    proxy = Proxy.query.get_or_404(proxy_id)
    
    try:
        # Use certbot to generate certificate
        cmd = [
            'certbot', 'certonly', '--standalone', '--non-interactive',
            '--agree-tos', '-m', email, '-d', domain
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            # Update proxy with certificate info
            proxy.tls_domain = domain
            db.session.commit()
            
            log_activity("Generate Certificate", f"Generated Let's Encrypt certificate for {domain}")
            return jsonify({
                'success': True,
                'message': f'Certificate generated successfully for {domain}'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Certificate generation failed: {result.stderr}'
            })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error generating certificate: {str(e)}'
        })

@proxy_tls_bp.route('/renew-cert', methods=['POST'])
@login_required
def renew_certificate():
    """Renew Let's Encrypt certificate"""
    proxy_id = request.form.get('proxy_id', type=int)
    
    if not proxy_id:
        return jsonify({'success': False, 'message': 'Proxy ID is required'})
    
    proxy = Proxy.query.get_or_404(proxy_id)
    
    if not proxy.tls_domain:
        return jsonify({'success': False, 'message': 'No domain configured for this proxy'})
    
    try:
        # Renew certificate
        cmd = ['certbot', 'renew', '--non-interactive']
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            log_activity("Renew Certificate", f"Renewed certificate for {proxy.tls_domain}")
            return jsonify({
                'success': True,
                'message': f'Certificate renewed successfully for {proxy.tls_domain}'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Certificate renewal failed: {result.stderr}'
            })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error renewing certificate: {str(e)}'
        })