import sys
import shutil
import subprocess
import threading
import time
import ipaddress
from flask import request
from app.extensions import db
from app.models import ActivityLog, Settings

_geo_lock = threading.Lock()
_geo_cache = {}
_geo_cache_expiry = {}

def log_activity(action, details=None):
    try:
        ip = request.remote_addr if request else 'CLI'
        log = ActivityLog(action=action, details=details, ip_address=ip)
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"Logging Error: {e}")

def get_setting(key, default=None):
    s = Settings.query.filter_by(key=key).first()
    return s.value if s else default

def set_setting(key, value):
    s = Settings.query.filter_by(key=key).first()
    if not s:
        s = Settings(key=key)
        db.session.add(s)
    s.value = value
    db.session.commit()

def _is_private_ip(ip_str):
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        return ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local
    except Exception:
        return False

def _lookup_country(ip_str):
    if not ip_str or _is_private_ip(ip_str):
        return "Local"
    now = time.time()
    with _geo_lock:
        if ip_str in _geo_cache and _geo_cache_expiry.get(ip_str, 0) > now:
            return _geo_cache[ip_str]
    country = "Unknown"
    try:
        if sys.platform.startswith('linux') and shutil.which("geoiplookup"):
            out = subprocess.check_output(["geoiplookup", ip_str], timeout=1).decode(errors='ignore').strip()
            if ":" in out:
                country = out.split(":", 1)[1].strip()
    except Exception:
        country = "Unknown"
    with _geo_lock:
        _geo_cache[ip_str] = country
        _geo_cache_expiry[ip_str] = now + 86400
    return country

def _format_duration(seconds):
    if seconds < 0:
        seconds = 0
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02}:{m:02}:{s:02}"
    return f"{m:02}:{s:02}"

def _quota_usage_bytes(proxy):
    if not proxy.quota_start:
        # Fallback for proxies without quota_start (e.g. unlimited ones created before update)
        # Return total usage
        return int(proxy.upload or 0) + int(proxy.download or 0)
    
    used_upload = max(0, int(proxy.upload) - int(proxy.quota_base_upload or 0))
    used_download = max(0, int(proxy.download) - int(proxy.quota_base_download or 0))
    return used_upload + used_download
