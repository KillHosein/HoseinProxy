import sys
import shutil
import subprocess
import threading
import time
import ipaddress
import re
from urllib.parse import urlparse
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

def _is_hex(s):
    if not s:
        return False
    return bool(re.fullmatch(r"[0-9a-fA-F]+", s))

def normalize_tls_domain(raw):
    d = (raw or "").strip()
    if not d:
        return None
    if "://" in d:
        try:
            u = urlparse(d)
            d = u.hostname or ""
        except Exception:
            d = d.split("://", 1)[-1]
    d = d.strip()
    if "/" in d:
        d = d.split("/", 1)[0]
    if ":" in d:
        d = d.split(":", 1)[0]
    d = d.strip().strip(".").lower()
    if d.startswith("*."):
        d = d[2:]
    if not d:
        return None
    try:
        d = d.encode("idna").decode("ascii").lower()
    except Exception:
        return None
    if len(d) > 253:
        return None
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,61}[a-z0-9]", d):
        return None
    return d

def infer_proxy_type_from_secret(secret):
    s = (secret or "").strip().lower()
    if s.startswith("ee"):
        return "tls"
    if s.startswith("dd"):
        return "dd"
    return "standard"

def extract_tls_domain_from_ee_secret(secret):
    s = (secret or "").strip().lower()
    if not s.startswith("ee"):
        return None
    payload = s[2:]
    if len(payload) <= 32:
        return None
    base = payload[:32]
    domain_hex = payload[32:]
    if not _is_hex(base) or not _is_hex(domain_hex) or len(domain_hex) % 2 != 0:
        return None
    try:
        domain_bytes = bytes.fromhex(domain_hex)
        domain = domain_bytes.decode("utf-8", errors="strict")
    except Exception:
        return None
    return normalize_tls_domain(domain)

def normalize_mtproxy_secret(proxy_type, secret, tls_domain=None):
    ptype = (proxy_type or "standard").strip().lower()
    s = (secret or "").strip().lower().replace(" ", "")
    if s.startswith("0x"):
        s = s[2:]
    if ptype not in {"standard", "dd", "tls"}:
        ptype = infer_proxy_type_from_secret(s)

    if ptype == "standard":
        if not _is_hex(s) or len(s) != 32:
            raise ValueError("Secret باید دقیقاً ۳۲ کاراکتر hex باشد.")
        return s

    if ptype == "dd":
        if s.startswith("dd"):
            base = s[2:]
        else:
            base = s
        if not _is_hex(base) or len(base) != 32:
            raise ValueError("Secret در حالت DD باید ۳۲ کاراکتر hex باشد (با یا بدون پیشوند dd).")
        return "dd" + base

    if s.startswith("ee"):
        payload = s[2:]
        if len(payload) < 34:
            raise ValueError("Secret در حالت FakeTLS نامعتبر است.")
        base = payload[:32]
        domain_hex = payload[32:]
        if not _is_hex(base) or not _is_hex(domain_hex) or len(domain_hex) % 2 != 0:
            raise ValueError("Secret در حالت FakeTLS باید hex معتبر باشد.")
        if tls_domain:
            norm_domain = normalize_tls_domain(tls_domain)
            if not norm_domain:
                raise ValueError("دامنه FakeTLS نامعتبر است.")
            expected_hex = norm_domain.encode("utf-8").hex()
            return "ee" + base + expected_hex
        return "ee" + base + domain_hex

    base = s
    if not _is_hex(base) or len(base) != 32:
        raise ValueError("Secret در حالت FakeTLS باید ۳۲ کاراکتر hex (بدون ee) باشد.")
    norm_domain = normalize_tls_domain(tls_domain) if tls_domain else None
    if not norm_domain:
        raise ValueError("دامنه FakeTLS نامعتبر است.")
    domain_hex = norm_domain.encode("utf-8").hex()
    return "ee" + base + domain_hex
