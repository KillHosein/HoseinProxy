#!/usr/bin/env python3
"""
Enhanced MTProto Proxy with FakeTLS Support
Integrates with existing panel for easy management
"""

import os
import subprocess
import json
import secrets
from pathlib import Path

class MTProtoFakeTLS:
    def __init__(self):
        self.project_dir = Path("/opt/mtproto-faketls")
        self.popular_domains = [
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
    
    def create_docker_compose(self, port, secret, domain, workers=4, tag=None):
        """Create Docker Compose configuration"""
        domain_hex = domain.encode('utf-8').hex()
        fake_secret = f"ee{secret}{domain_hex}"
        
        compose_config = f"""version: '3.8'

services:
  mtproto-faketls-{port}:
    image: golang:1.21-alpine
    container_name: mtproto_faketls_{port}
    restart: always
    ports:
      - "{port}:443"
    command: |
      sh -c "
        apk add --no-cache git openssl &&
        git clone https://github.com/TelegramMessenger/MTProxy.git /app &&
        cd /app &&
        go mod init mtproxy || true &&
        go mod tidy || true &&
        CGO_ENABLED=0 GOOS=linux go build -o mtproto-proxy ./cmd/proxy &&
        mkdir -p /etc/ssl/certs /etc/ssl/private /var/log/mtproto &&
        openssl genrsa -out /etc/ssl/private/privkey.pem 2048 &&
        openssl req -new -key /etc/ssl/private/privkey.pem -out /tmp/cert.csr -subj '/C=US/ST=CA/L=Mountain View/O=Google LLC/CN={domain}' &&
        openssl x509 -req -days 3650 -in /tmp/cert.csr -signkey /etc/ssl/private/privkey.pem -out /etc/ssl/certs/fullchain.pem &&
        rm -f /tmp/cert.csr &&
        ./mtproto-proxy \\
          -u nobody \\
          -p 8888,80,443 \\
          -H 443 \\
          -S {fake_secret} \\
          --address 0.0.0.0 \\
          --port 443 \\
          --http-ports 80 \\
          --slaves {workers} \\
          --max-special-connections 60000 \\
          --allow-skip-dh \\
          --cert /etc/ssl/certs/fullchain.pem \\
          --key /etc/ssl/private/privkey.pem \\
          --dc 1,149.154.175.50,443 \\
          --dc 2,149.154.167.51,443 \\
          --dc 3,149.154.175.100,443 \\
          --dc 4,149.154.167.91,443 \\
          --dc 5,91.108.56.151,443 \\
          {f'--tag {tag}' if tag else ''}
      "
    volumes:
      - ./logs:/var/log/mtproto
    networks:
      - mtproto_network

networks:
  mtproto_network:
    driver: bridge
"""
        return compose_config
    
    def setup_proxy(self, port, domain, workers=4, tag=None):
        """Set up a new FakeTLS proxy"""
        try:
            # Create project directory
            self.project_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate secret
            secret = secrets.token_hex(16)
            
            # Create Docker Compose file
            compose_content = self.create_docker_compose(port, secret, domain, workers, tag)
            
            compose_file = self.project_dir / f"docker-compose-{port}.yml"
            with open(compose_file, 'w') as f:
                f.write(compose_content)
            
            # Start the proxy
            cmd = ['docker-compose', '-f', str(compose_file), 'up', '-d']
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.project_dir))
            
            if result.returncode == 0:
                # Get server IP
                try:
                    server_ip = subprocess.check_output(['curl', '-s', 'ifconfig.me']).decode().strip()
                except:
                    server_ip = "YOUR_SERVER_IP"
                
                # Generate proxy links
                domain_hex = domain.encode('utf-8').hex()
                fake_secret = f"ee{secret}{domain_hex}"
                
                telegram_link = f"https://t.me/proxy?server={server_ip}&port={port}&secret={fake_secret}"
                direct_link = f"tg://proxy?server={server_ip}&port={port}&secret={fake_secret}"
                
                # Save info
                info_file = self.project_dir / f"proxy-{port}-info.txt"
                with open(info_file, 'w') as f:
                    f.write(f"MTProto FakeTLS Proxy Information\n")
                    f.write(f"==============================\n")
                    f.write(f"Domain: {domain}\n")
                    f.write(f"Port: {port}\n")
                    f.write(f"Secret: {secret}\n")
                    f.write(f"Fake Secret: {fake_secret}\n")
                    f.write(f"Workers: {workers}\n")
                    f.write(f"Tag: {tag or 'None'}\n")
                    f.write(f"Server IP: {server_ip}\n")
                    f.write(f"\nTelegram Link:\n{telegram_link}\n")
                    f.write(f"\nDirect Link:\n{direct_link}\n")
                    f.write(f"\nDocker Compose: {compose_file}\n")
                
                return {
                    'success': True,
                    'port': port,
                    'domain': domain,
                    'secret': secret,
                    'fake_secret': fake_secret,
                    'telegram_link': telegram_link,
                    'direct_link': direct_link,
                    'info_file': str(info_file)
                }
            else:
                return {
                    'success': False,
                    'error': f"Docker Compose failed: {result.stderr}"
                }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def stop_proxy(self, port):
        """Stop a FakeTLS proxy"""
        try:
            compose_file = self.project_dir / f"docker-compose-{port}.yml"
            if compose_file.exists():
                cmd = ['docker-compose', '-f', str(compose_file), 'down']
                result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.project_dir))
                return result.returncode == 0
            return False
        except:
            return False
    
    def get_proxy_status(self, port):
        """Get status of a FakeTLS proxy"""
        try:
            compose_file = self.project_dir / f"docker-compose-{port}.yml"
            if compose_file.exists():
                cmd = ['docker-compose', '-f', str(compose_file), 'ps']
                result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.project_dir))
                return 'Up' in result.stdout
            return False
        except:
            return False
    
    def get_proxy_logs(self, port, lines=50):
        """Get logs for a FakeTLS proxy"""
        try:
            compose_file = self.project_dir / f"docker-compose-{port}.yml"
            if compose_file.exists():
                cmd = ['docker-compose', '-f', str(compose_file), 'logs', '--tail', str(lines)]
                result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.project_dir))
                return result.stdout
            return ""
        except:
            return ""

# CLI interface
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python faketls_manager.py {setup|stop|status|logs} [port] [domain] [workers] [tag]")
        print("Example: python faketls_manager.py setup 443 google.com 4 mytag")
        sys.exit(1)
    
    manager = MTProtoFakeTLS()
    command = sys.argv[1]
    
    if command == "setup" and len(sys.argv) >= 4:
        port = int(sys.argv[2])
        domain = sys.argv[3]
        workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4
        tag = sys.argv[5] if len(sys.argv) > 5 else None
        
        result = manager.setup_proxy(port, domain, workers, tag)
        if result['success']:
            print(f"✅ FakeTLS proxy setup successful!")
            print(f"Port: {result['port']}")
            print(f"Domain: {result['domain']}")
            print(f"Telegram Link: {result['telegram_link']}")
            print(f"Info saved to: {result['info_file']}")
        else:
            print(f"❌ Setup failed: {result['error']}")
    
    elif command == "stop" and len(sys.argv) >= 3:
        port = int(sys.argv[2])
        success = manager.stop_proxy(port)
        print(f"{'✅' if success else '❌'} Proxy stopped" if success else "Failed to stop proxy")
    
    elif command == "status" and len(sys.argv) >= 3:
        port = int(sys.argv[2])
        status = manager.get_proxy_status(port)
        print(f"Proxy on port {port}: {'🟢 Running' if status else '🔴 Stopped'}")
    
    elif command == "logs" and len(sys.argv) >= 3:
        port = int(sys.argv[2])
        lines = int(sys.argv[3]) if len(sys.argv) > 3 else 50
        logs = manager.get_proxy_logs(port, lines)
        print(logs)
    
    else:
        print("Invalid command or arguments")