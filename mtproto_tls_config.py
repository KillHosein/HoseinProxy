#!/usr/bin/env python3
"""
MTProto TLS Configuration Generator
This script generates TLS configuration for MTProto proxies
"""

import os
import sys
import json
import secrets
import subprocess
from pathlib import Path

class MTProtoTLSConfig:
    def __init__(self, domain, email=None, secret=None, workers=4, tag=None):
        self.domain = domain
        self.email = email or f"admin@{domain}"
        self.secret = secret or secrets.token_hex(16)
        self.workers = workers
        self.tag = tag
        
    def generate_docker_compose(self):
        """Generate Docker Compose configuration for TLS proxy"""
        compose_config = {
            'version': '3.8',
            'services': {
                'nginx': {
                    'image': 'nginx:alpine',
                    'container_name': 'mtproto_nginx',
                    'restart': 'always',
                    'ports': ['80:80', '443:443'],
                    'volumes': [
                        './nginx/conf.d:/etc/nginx/conf.d',
                        './nginx/ssl:/etc/nginx/ssl',
                        './nginx/logs:/var/log/nginx',
                        'certbot_data:/etc/letsencrypt',
                        'certbot_www:/var/www/certbot'
                    ],
                    'depends_on': ['mtproto_tls'],
                    'networks': ['mtproto_network']
                },
                'certbot': {
                    'image': 'certbot/certbot',
                    'container_name': 'certbot',
                    'volumes': [
                        'certbot_data:/etc/letsencrypt',
                        'certbot_www:/var/www/certbot'
                    ],
                    'entrypoint': "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"
                },
                'mtproto_tls': {
                    'build': {
                        'context': '.',
                        'dockerfile': 'Dockerfile.tls'
                    },
                    'container_name': 'mtproto_tls_proxy',
                    'restart': 'always',
                    'expose': ['443'],
                    'environment': {
                        'SECRET': self.secret,
                        'TAG': self.tag or '',
                        'WORKERS': self.workers,
                        'TLS_DOMAIN': self.domain,
                        'TLS_CERT_PATH': '/etc/ssl/certs/fullchain.pem',
                        'TLS_KEY_PATH': '/etc/ssl/private/privkey.pem'
                    },
                    'volumes': [
                        './ssl:/etc/ssl/certs:ro',
                        './logs:/var/log/mtproto'
                    ],
                    'networks': ['mtproto_network']
                }
            },
            'networks': {
                'mtproto_network': {'driver': 'bridge'}
            },
            'volumes': {
                'certbot_data': None,
                'certbot_www': None
            }
        }
        return compose_config
    
    def generate_nginx_config(self):
        """Generate Nginx configuration for TLS proxy"""
        nginx_config = f"""# MTProto TLS Proxy Nginx Configuration

upstream mtproto_backend {{
    server mtproto_tls_proxy:443;
    keepalive 32;
}}

# HTTP to HTTPS redirect
server {{
    listen 80;
    server_name {self.domain};
    
    # Let's Encrypt challenge
    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}
    
    # Redirect all other traffic to HTTPS
    location / {{
        return 301 https://$host$request_uri;
    }}
}}

# HTTPS server with TLS
server {{
    listen 443 ssl http2;
    server_name {self.domain};
    
    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/{self.domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{self.domain}/privkey.pem;
    
    # Modern SSL Configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    
    # SSL Session Configuration
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;
    
    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    
    # Security Headers
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Referrer-Policy "strict-origin-when-cross-origin";
    
    # MTProto specific configuration
    location / {{
        proxy_pass https://mtproto_backend;
        proxy_ssl_verify off;
        
        # WebSocket support for MTProto
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Proxy headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Buffer settings
        proxy_buffering off;
        proxy_request_buffering off;
        
        # Keepalive
        proxy_set_header Connection "";
    }}
    
    # Health check endpoint
    location /health {{
        access_log off;
        return 200 "healthy\\n";
        add_header Content-Type text/plain;
    }}
}}"""
        return nginx_config
    
    def generate_proxy_link(self):
        """Generate Telegram proxy link"""
        domain_hex = self.domain.encode('utf-8').hex()
        return f"https://t.me/proxy?server={self.domain}&port=443&secret=ee{self.secret}{domain_hex}"
    
    def save_configuration(self):
        """Save all configuration files"""
        # Create directories
        Path("nginx/conf.d").mkdir(parents=True, exist_ok=True)
        Path("ssl").mkdir(exist_ok=True)
        Path("logs").mkdir(exist_ok=True)
        
        # Save Docker Compose
        import yaml
        with open("docker-compose.yml", "w") as f:
            yaml.dump(self.generate_docker_compose(), f, default_flow_style=False)
        
        # Save Nginx config
        with open("nginx/conf.d/mtproto-tls.conf", "w") as f:
            f.write(self.generate_nginx_config())
        
        # Save environment file
        with open(".env", "w") as f:
            f.write(f"DOMAIN={self.domain}\n")
            f.write(f"SECRET={self.secret}\n")
            f.write(f"WORKERS={self.workers}\n")
            f.write(f"TAG={self.tag or ''}\n")
            f.write(f"TLS_DOMAIN={self.domain}\n")
        
        # Save proxy info
        proxy_link = self.generate_proxy_link()
        with open("proxy_info.txt", "w") as f:
            f.write(f"MTProto TLS Proxy Information\n")
            f.write(f"==============================\n")
            f.write(f"Domain: {self.domain}\n")
            f.write(f"Secret: {self.secret}\n")
            f.write(f"Workers: {self.workers}\n")
            f.write(f"Tag: {self.tag or 'None'}\n")
            f.write(f"Proxy Link: {proxy_link}\n")
            f.write(f"==============================\n\n")
            f.write(f"Docker Commands:\n")
            f.write(f"- View logs: docker-compose logs -f\n")
            f.write(f"- Stop services: docker-compose down\n")
            f.write(f"- Restart services: docker-compose restart\n")
            f.write(f"- Update certificates: docker-compose exec certbot certbot renew\n")
        
        return proxy_link

def main():
    if len(sys.argv) < 2:
        print("Usage: python mtproto_tls_config.py <domain> [email] [secret] [workers] [tag]")
        print("Example: python mtproto_tls_config.py proxy.yourdomain.com admin@yourdomain.com")
        sys.exit(1)
    
    domain = sys.argv[1]
    email = sys.argv[2] if len(sys.argv) > 2 else None
    secret = sys.argv[3] if len(sys.argv) > 3 else None
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    tag = sys.argv[5] if len(sys.argv) > 5 else None
    
    config = MTProtoTLSConfig(domain, email, secret, workers, tag)
    proxy_link = config.save_configuration()
    
    print(f"✅ TLS configuration generated successfully!")
    print(f"📋 Configuration files created:")
    print(f"   - docker-compose.yml")
    print(f"   - nginx/conf.d/mtproto-tls.conf")
    print(f"   - .env")
    print(f"   - proxy_info.txt")
    print(f"")
    print(f"🔗 Proxy Link: {proxy_link}")
    print(f"")
    print(f"To start the proxy:")
    print(f"1. Run: docker-compose up -d")
    print(f"2. Get Let's Encrypt certificate: docker-compose exec certbot certbot certonly --standalone -d {domain}")
    print(f"3. Reload nginx: docker-compose exec nginx nginx -s reload")

if __name__ == "__main__":
    main()