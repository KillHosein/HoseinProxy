# HoseinProxy Documentation

## Introduction
HoseinProxy is a comprehensive management system for Telegram MTProto proxies. It provides a web-based interface for managing proxies, monitoring traffic, and handling system operations.

## Features
- **Proxy Management**: Create, start, stop, and delete proxies.
- **Traffic Monitoring**: Real-time traffic stats (Upload/Download) via Docker API.
- **User Management**: Secure login system with rate limiting.
- **System Management**: Update, backup, and restart services directly from the web UI.
- **CLI Tools**: `manage.sh` for advanced system administration.

## Installation

### Prerequisites
- Ubuntu 20.04 or later
- Root access
- Git

### Quick Install
```bash
git clone https://github.com/KillHosein/HoseinProxy.git
cd HoseinProxy
chmod +x manage.sh
./manage.sh
```
Select "1" to install.

## Web Interface
After installation, access the panel at `http://YOUR_SERVER_IP`.

### Dashboard
- View all proxies and their status.
- Monitor real-time traffic usage.
- Create new proxies with custom secrets and ports.

### Settings
- Configure server IP and domain for link generation.

### System
- **Check Update**: Checks for new versions from GitHub.
- **Restart Service**: Restarts the panel service.
- **Backup**: Creates a snapshot of the database and config.
- **Logs**: View system logs for troubleshooting.

## CLI Management (`manage.sh`)
Run `./manage.sh` to access the main menu:

1. **Install Panel**: Installs dependencies and sets up the service.
2. **Update Panel**: Updates the code from GitHub.
3. **Uninstall Panel**: Removes the service and files (with backup option).
4. **Restart Service**: Restarts the `hoseinproxy` systemd service.
5. **View Logs**: Tails the installation/operation log.
6. **Schedule Updates**: Enables/Disables daily auto-updates via cron.
7. **Backup Data**: Manually triggers a backup.
8. **Rollback Version**: Reverts to the previous Git commit.

## API Reference
The panel provides a few internal API endpoints:

- `GET /api/stats`: Returns current system metrics (CPU, RAM, Disk).
- `GET /api/history`: Returns historical traffic data for charts.

## Troubleshooting
- **Login Failed**: Ensure you are using the correct credentials. Use `python3 -c "from app import create_admin; create_admin('user', 'pass')"` to reset.
- **Docker Error**: Ensure Docker is running (`systemctl status docker`).
- **Update Failed**: Check internet connection and Git status.

## Security
- **Rate Limiting**: Login attempts are limited to 10 per minute.
- **Secrets**: Proxy secrets are generated securely using `secrets.token_hex`.
- **Nginx**: Used as a reverse proxy for better performance and security.

## License
MIT License
