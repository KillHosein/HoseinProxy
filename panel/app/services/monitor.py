import time
import datetime
import threading
import sys
import os
import subprocess
import requests
import psutil
from collections import defaultdict
from app.extensions import db
from app.models import Proxy, ProxyStats, Alert, BlockedIP, Settings
from app.services.docker_client import client as docker_client
from app.services.firewall_service import _sync_firewall, _apply_firewall_rule
from app.utils.helpers import log_activity, get_setting, _lookup_country, _format_duration, _quota_usage_bytes
from app.services.telegram_service import send_telegram_alert

_live_connections_lock = threading.Lock()
_live_connections = defaultdict(list)
_conn_first_seen = {}
_rate_lock = threading.Lock()
_last_bytes = {}
_alerts_lock = threading.Lock()
_last_alert_by_key = {}

def _maybe_emit_alert(proxy_id, severity, message, key, cooldown_seconds=60):
    now = datetime.datetime.utcnow()
    with _alerts_lock:
        last = _last_alert_by_key.get(key)
        if last and (now - last).total_seconds() < cooldown_seconds:
            return
        _last_alert_by_key[key] = now
    try:
        alert = Alert(proxy_id=proxy_id, severity=severity, message=message)
        db.session.add(alert)
        db.session.commit()
        
        if severity in ['warning', 'error', 'critical']:
            send_telegram_alert(f"⚠️ Alert [{severity.upper()}]\n{message}")
            
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

def _check_proxy_limits(proxies):
    now = datetime.datetime.utcnow()
    for p in proxies:
        if p.status != 'running':
            continue
            
        should_stop = False
        reason = ""
        
        # Check Expiry
        if p.expiry_date and now > p.expiry_date:
            should_stop = True
            reason = "Expired"
            
        # Check Quota
        elif p.quota_bytes and p.quota_bytes > 0:
            used = _quota_usage_bytes(p) or 0
            if used >= p.quota_bytes:
                should_stop = True
                reason = "Quota Exceeded"
        
        if should_stop:
            try:
                if docker_client and p.container_id:
                    container = docker_client.containers.get(p.container_id)
                    container.stop()
                p.status = "stopped"
                log_activity("Auto-Stop", f"Proxy {p.port} stopped due to {reason}")
                _maybe_emit_alert(p.id, "warning", f"پروکسی {p.port} به دلیل {reason} متوقف شد.", f"autostop:{p.id}")
            except Exception as e:
                print(f"Error auto-stopping proxy {p.port}: {e}")

def _check_system_health():
    """Checks system resources and emits alerts if thresholds are exceeded."""
    try:
        # CPU Check
        cpu_percent = psutil.cpu_percent(interval=None)
        if cpu_percent > 90:
            _maybe_emit_alert(None, "critical", f"مصرف پردازنده بسیار بالاست: {cpu_percent}%", "sys_cpu_high", cooldown_seconds=300)
        elif cpu_percent > 80:
            _maybe_emit_alert(None, "warning", f"مصرف پردازنده بالاست: {cpu_percent}%", "sys_cpu_high", cooldown_seconds=900)

        # RAM Check
        mem = psutil.virtual_memory()
        if mem.percent > 90:
            _maybe_emit_alert(None, "critical", f"حافظه رم در حال اتمام است: {mem.percent}%", "sys_mem_high", cooldown_seconds=300)
        elif mem.percent > 80:
             _maybe_emit_alert(None, "warning", f"مصرف رم بالاست: {mem.percent}%", "sys_mem_high", cooldown_seconds=900)

        # Disk Check
        disk = psutil.disk_usage('/')
        if disk.percent > 90:
             _maybe_emit_alert(None, "critical", f"فضای دیسک پر شده است: {disk.percent}%", "sys_disk_high", cooldown_seconds=3600)
             
    except Exception as e:
        print(f"Health Check Error: {e}")

def update_docker_stats(app):
    """Periodically updates proxy traffic stats from Docker"""
    # Wait for tables to be created
    while True:
        try:
            with app.app_context():
                # Assuming DB is initialized by main thread
                _sync_firewall()
                break
        except:
            time.sleep(2)
            
    last_stats_sample = datetime.datetime.utcnow() - datetime.timedelta(minutes=2)
    last_health_check = datetime.datetime.utcnow()
    
    while True:
        try:
            with app.app_context():
                # Run Health Check every 30 seconds
                if (datetime.datetime.utcnow() - last_health_check).total_seconds() > 30:
                    _check_system_health()
                    last_health_check = datetime.datetime.utcnow()

                if docker_client:
                    proxies = Proxy.query.filter(Proxy.container_id != None).all()
                    
                    try:
                        all_connections = psutil.net_connections(kind='tcp')
                    except Exception:
                        all_connections = []
                    
                    for p in proxies:
                        try:
                            container = docker_client.containers.get(p.container_id)
                            
                            # 2. Interface Stats (Docker API / IPTables)
                            rx = 0
                            tx = 0
                            iptables_success = False
                            
                            if sys.platform.startswith('linux'):
                                try:
                                    container_ip = container.attrs.get('NetworkSettings', {}).get('IPAddress')
                                    if not container_ip:
                                        nets = container.attrs.get('NetworkSettings', {}).get('Networks', {})
                                        if nets:
                                            container_ip = list(nets.values())[0].get('IPAddress')
                                    
                                    if container_ip:
                                        cmd = "iptables -nvx -L FORWARD"
                                        output = subprocess.check_output(cmd, shell=True).decode()
                                        
                                        ipt_client_upload = 0   
                                        ipt_total_tx = 0        
                                        ipt_total_rx = 0        
                                        
                                        for line in output.split('\n'):
                                            if container_ip in line:
                                                parts = line.split()
                                                if len(parts) >= 8:
                                                    try:
                                                        b = int(parts[1])
                                                        src = parts[7]
                                                        dst = parts[8]
                                                        
                                                        if dst == container_ip:
                                                            ipt_total_rx += b
                                                            # if f"dpt:{p.port}" in line:
                                                            #     ipt_client_upload += b
                                                        elif src == container_ip:
                                                            ipt_total_tx += b
                                                    except:
                                                        pass
                                        
                                        if ipt_total_rx > 0 or ipt_total_tx > 0:
                                            # MTProto Proxy traffic logic:
                                            # RX (Docker perspective) = Client Upload + TG Server Download
                                            # TX (Docker perspective) = Client Download + TG Server Upload
                                            
                                            # Since it's a proxy, almost all traffic is forwarded.
                                            # Client Download ~= TG Server Download
                                            # Client Upload ~= TG Server Upload
                                            
                                            # Total Traffic passing through interface = Client Upload + Client Download + TG Upload + TG Download
                                            # ~= 2 * (Client Upload + Client Download)
                                            
                                            # So we should divide by 2 to get approximate user usage.
                                            
                                            rx = int(ipt_total_rx / 2)
                                            tx = int(ipt_total_tx / 2)
                                            iptables_success = True
                                except Exception:
                                    pass

                            # 3. Fallback to Docker Stats
                            if not iptables_success:
                                stats = container.stats(stream=False)
                                networks = stats.get('networks', {})
                                raw_rx = 0
                                raw_tx = 0
                                for iface, data in networks.items():
                                    raw_rx += data.get('rx_bytes', 0)
                                    raw_tx += data.get('tx_bytes', 0)
                                
                                # Apply same logic for Docker stats
                                rx = int(raw_rx / 2)
                                tx = int(raw_tx / 2)
                            
                            p.download = rx
                            p.upload = tx

                            with _rate_lock:
                                prev = _last_bytes.get(p.id)
                                _last_bytes[p.id] = (tx, rx, time.time())
                            if prev:
                                prev_tx, prev_rx, prev_time = prev
                                dt = max(1e-3, time.time() - prev_time)
                                p.upload_rate_bps = int(max(0, tx - prev_tx) / dt)
                                p.download_rate_bps = int(max(0, rx - prev_rx) / dt)
                            else:
                                p.upload_rate_bps = 0
                                p.download_rate_bps = 0
                                
                            if p.quota_start and (p.quota_base_upload == 0 and p.quota_base_download == 0):
                                p.quota_base_upload = int(tx)
                                p.quota_base_download = int(rx)
                            
                            # 2. Update Active Connections
                            conns = [c for c in all_connections if c.laddr.port == p.port and c.status == 'ESTABLISHED']
                            count = len(conns)

                            if count == 0 and sys.platform.startswith('linux'):
                                try:
                                    cmd = f"ss -tnH state established sport = :{p.port} | wc -l"
                                    output = subprocess.check_output(cmd, shell=True).decode().strip()
                                    if output.isdigit() and int(output) > 0:
                                        count = int(output)
                                except Exception:
                                    pass

                            p.active_connections = count
                                
                        except Exception:
                            continue
                    
                    if proxies:
                        _check_proxy_limits(proxies)
                        db.session.commit()
                    
                    now = datetime.datetime.utcnow()
                    if (now - last_stats_sample).total_seconds() >= 60:
                        for p in proxies:
                            stat = ProxyStats(
                                proxy_id=p.id,
                                upload=p.upload,
                                download=p.download,
                                active_connections=p.active_connections,
                                timestamp=now
                            )
                            db.session.add(stat)
                        db.session.commit()
                        last_stats_sample = now
                        cutoff = now - datetime.timedelta(days=30)
                        ProxyStats.query.filter(ProxyStats.timestamp < cutoff).delete()
                        Alert.query.filter(Alert.created_at < cutoff).delete()
                        db.session.commit()

                    now_epoch = time.time()
                    new_live = defaultdict(list)
                    ip_counts = defaultdict(int)
                    current_conn_keys = set()
                    for p in proxies:
                        conns = [c for c in all_connections if c.laddr.port == p.port and c.status == 'ESTABLISHED']
                        for c in conns:
                            if not c.raddr:
                                continue
                            ip = getattr(c.raddr, "ip", None) or c.raddr[0]
                            rport = getattr(c.raddr, "port", None) or c.raddr[1]
                            conn_key = (p.id, ip, int(rport), int(p.port))
                            current_conn_keys.add(conn_key)
                            first_seen = _conn_first_seen.get(conn_key)
                            if not first_seen:
                                _conn_first_seen[conn_key] = now_epoch
                                first_seen = now_epoch
                            ip_counts[(p.id, ip)] += 1
                            new_live[p.id].append({
                                "ip": ip,
                                "country": _lookup_country(ip),
                                "connected_for": _format_duration(now_epoch - first_seen),
                                "connected_for_seconds": int(now_epoch - first_seen),
                                "remote_port": int(rport)
                            })
                    with _live_connections_lock:
                        _live_connections.clear()
                        _live_connections.update(new_live)
                        to_del = [k for k in _conn_first_seen.keys() if k not in current_conn_keys]
                        for k in to_del:
                            _conn_first_seen.pop(k, None)

                    alert_total_threshold = int(get_setting("alert_conn_threshold", "300") or 300)
                    alert_per_ip_threshold = int(get_setting("alert_ip_conn_threshold", "20") or 20)
                    for p in proxies:
                        if p.active_connections >= alert_total_threshold:
                            _maybe_emit_alert(p.id, "warning", f"اتصالات غیرعادی روی پورت {p.port}: {p.active_connections}", f"total:{p.id}")
                        for (pid, ip), cnt in ip_counts.items():
                            if pid != p.id:
                                continue
                            if cnt >= alert_per_ip_threshold:
                                _maybe_emit_alert(p.id, "warning", f"اتصالات زیاد از یک IP روی پورت {p.port}: {ip} ({cnt})", f"ip:{p.id}:{ip}")
                                
                                # Auto-Block Logic
                                try:
                                    auto_block = get_setting('auto_block_enabled', '0') == '1'
                                    if auto_block:
                                        if not BlockedIP.query.filter_by(ip_address=ip).first():
                                            b = BlockedIP(ip_address=ip, reason=f"Auto-Block: {cnt} connections on port {p.port}")
                                            db.session.add(b)
                                            db.session.commit()
                                            _apply_firewall_rule(ip, 'block')
                                            log_activity("Auto-Block", f"Blocked IP {ip} due to high connections")
                                            send_telegram_alert(f"🚫 Auto-Blocked IP {ip}\nReason: High connections ({cnt}) on port {p.port}")
                                except Exception as e:
                                    print(f"Auto-Block Error: {e}")

        except Exception as e:
            print(f"Stats Loop Error: {e}")
        
        time.sleep(3)
