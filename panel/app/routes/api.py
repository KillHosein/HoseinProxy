import time
import subprocess
import sys
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Blueprint, jsonify, request
from flask_login import login_required
from sqlalchemy import func
import psutil
from app.models import Proxy, ProxyStats, Alert, ActivityLog
from app.extensions import db
from app.utils.helpers import _quota_usage_bytes, get_setting
from app.services.monitor import _live_connections, _live_connections_lock

api_bp = Blueprint('api', __name__, url_prefix='/api')

def get_system_metrics():
    """Returns system metrics for the API"""
    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        load_avg = [round(x, 2) for x in psutil.getloadavg()] if hasattr(psutil, 'getloadavg') else [0, 0, 0]
        
        return {
            "cpu": cpu,
            "mem_percent": mem.percent,
            "mem_used": round(mem.used / (1024**3), 2),
            "mem_total": round(mem.total / (1024**3), 2),
            "disk_percent": disk.percent,
            "net_sent": round(net.bytes_sent / (1024**2), 2),
            "net_recv": round(net.bytes_recv / (1024**2), 2),
            "uptime": int(uptime_seconds),
            "load_avg": load_avg
        }
    except Exception as e:
        return {"error": str(e)}

@api_bp.route('/tools/speedtest', methods=['POST'])
@login_required
def speedtest():
    def run_speedtest():
        try:
            import speedtest
            st = speedtest.Speedtest()
            st.get_best_server()
            download = st.download() / 1_000_000 # Mbps
            upload = st.upload() / 1_000_000 # Mbps
            ping = st.results.ping
            return {"download": round(download, 2), "upload": round(upload, 2), "ping": round(ping, 2)}
        except Exception as e:
            return {"error": str(e)}
    result = run_speedtest()
    return jsonify(result)

@api_bp.route('/tools/ping', methods=['POST'])
@login_required
def ping():
    host = request.json.get('host', '8.8.8.8')
    try:
        if not all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_" for c in host):
             return jsonify({"output": "Invalid host format"})
             
        cmd = ['ping', '-c', '4', host] if sys.platform.startswith('linux') else ['ping', '-n', '4', host]
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode()
        return jsonify({"output": output})
    except subprocess.CalledProcessError as e:
        return jsonify({"output": e.output.decode()})
    except Exception as e:
        return jsonify({"output": str(e)})

@api_bp.route('/latency', methods=['GET'])
@login_required
def latency():
    import socket
    target = request.args.get('target', '8.8.8.8')
    port = 53
    timeout = 3
    try:
        start_time = time.time()
        s = socket.create_connection((target, port), timeout)
        s.close()
        end_time = time.time()
        latency_ms = round((end_time - start_time) * 1000, 2)
        return jsonify({'latency': latency_ms, 'status': 'success'})
    except Exception as e:
        return jsonify({'latency': -1, 'status': 'error', 'message': str(e)})

@api_bp.route('/latency', methods=['GET'])
@login_required
def latency():
    import socket
    target = request.args.get('target', '8.8.8.8')
    port = 53
    timeout = 3
    try:
        start_time = time.time()
        s = socket.create_connection((target, port), timeout)
        s.close()
        end_time = time.time()
        latency_ms = round((end_time - start_time) * 1000, 2)
        return jsonify({'latency': latency_ms, 'status': 'success'})
    except Exception as e:
        return jsonify({'latency': -1, 'status': 'error', 'message': str(e)})

@api_bp.route('/reports/top_ips')
@login_required
def reports_top_ips():
    with _live_connections_lock:
        all_conns = []
        for pid, conns in _live_connections.items():
            for c in conns:
                c['proxy_id'] = pid
                all_conns.append(c)
                
    ip_counts = defaultdict(int)
    ip_details = {}
    for c in all_conns:
        ip = c['ip']
        ip_counts[ip] += 1
        if ip not in ip_details:
            ip_details[ip] = c['country']
            
    sorted_ips = sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)[:20]
    
    result = []
    for ip, count in sorted_ips:
        result.append({
            "ip": ip,
            "country": ip_details.get(ip, "Unknown"),
            "connections": count
        })
        
    return jsonify(result)

@api_bp.route('/reports/traffic_by_tag')
@login_required
def reports_traffic_by_tag():
    proxies = Proxy.query.all()
    tag_stats = defaultdict(lambda: {'upload': 0, 'download': 0, 'count': 0})
    
    for p in proxies:
        tag = p.tag or "بدون تگ"
        tag_stats[tag]['upload'] += p.upload
        tag_stats[tag]['download'] += p.download
        tag_stats[tag]['count'] += 1
        
    result = []
    for tag, stats in tag_stats.items():
        result.append({
            "tag": tag,
            "upload_gb": round(stats['upload'] / (1024**3), 3),
            "download_gb": round(stats['download'] / (1024**3), 3),
            "total_gb": round((stats['upload'] + stats['download']) / (1024**3), 3),
            "proxy_count": stats['count']
        })
        
    result.sort(key=lambda x: x['total_gb'], reverse=True)
    return jsonify(result)

@api_bp.route('/stats')
@login_required
def stats():
    return jsonify(get_system_metrics())

@api_bp.route('/proxies')
@login_required
def proxies():
    proxies = Proxy.query.all()
    data = []
    for p in proxies:
        quota_used = _quota_usage_bytes(p)
        quota_remaining = None
        if p.quota_bytes and p.quota_bytes > 0 and quota_used is not None:
            quota_remaining = max(0, int(p.quota_bytes) - int(quota_used))
        data.append({
            'id': p.id,
            'status': p.status,
            'active_connections': p.active_connections,
            'upload': round(p.upload / (1024*1024), 2),
            'download': round(p.download / (1024*1024), 2),
            'upload_rate_mbps': round((p.upload_rate_bps * 8) / (1024*1024), 3),
            'download_rate_mbps': round((p.download_rate_bps * 8) / (1024*1024), 3),
            'quota_mb': round((p.quota_bytes or 0) / (1024*1024), 2),
            'quota_used_mb': round((quota_used or 0) / (1024*1024), 2) if quota_used is not None else None,
            'quota_remaining_mb': round((quota_remaining or 0) / (1024*1024), 2) if quota_remaining is not None else None,
            'name': p.name or p.tag
        })
    return jsonify(data)

@api_bp.route('/proxy/<int:proxy_id>/connections')
@login_required
def proxy_connections(proxy_id):
    ip_filter = (request.args.get("ip") or "").strip()
    country_filter = (request.args.get("country") or "").strip()
    with _live_connections_lock:
        items = list(_live_connections.get(proxy_id, []))
    if ip_filter:
        items = [it for it in items if ip_filter in (it.get("ip") or "")]
    if country_filter:
        items = [it for it in items if country_filter.lower() in (it.get("country") or "").lower()]
    items.sort(key=lambda x: x.get("connected_for_seconds", 0), reverse=True)
    return jsonify({
        "proxy_id": proxy_id,
        "active_connections": len(items),
        "items": items[:500]
    })

@api_bp.route('/proxy/<int:proxy_id>/connections_history')
@login_required
def proxy_connections_history(proxy_id):
    minutes = request.args.get("minutes", default=60, type=int)
    minutes = max(5, min(24 * 60, minutes))
    end = datetime.utcnow()
    start = end - timedelta(minutes=minutes)
    rows = ProxyStats.query.filter(
        ProxyStats.proxy_id == proxy_id,
        ProxyStats.timestamp >= start,
        ProxyStats.timestamp <= end
    ).order_by(ProxyStats.timestamp.asc()).all()
    labels = [r.timestamp.strftime('%H:%M') for r in rows]
    values = [int(r.active_connections or 0) for r in rows]
    return jsonify({"labels": labels, "values": values})

def _compute_usage_series(rows, granularity):
    if not rows:
        return {"labels": [], "upload_mb": [], "download_mb": []}
    rows = sorted(rows, key=lambda r: r.timestamp)
    groups = defaultdict(list)
    for r in rows:
        if granularity == "hourly":
            key = r.timestamp.strftime('%Y-%m-%d %H:00')
        elif granularity == "monthly":
            key = r.timestamp.strftime('%Y-%m')
        else:
            key = r.timestamp.strftime('%Y-%m-%d')
        groups[key].append(r)
    labels = []
    upload_mb = []
    download_mb = []
    for k in sorted(groups.keys()):
        items = groups[k]
        first = items[0]
        last = items[-1]
        du = max(0, int(last.upload or 0) - int(first.upload or 0))
        dd = max(0, int(last.download or 0) - int(first.download or 0))
        labels.append(k)
        upload_mb.append(round(du / (1024 * 1024), 2))
        download_mb.append(round(dd / (1024 * 1024), 2))
    return {"labels": labels, "upload_mb": upload_mb, "download_mb": download_mb}

@api_bp.route('/proxy/<int:proxy_id>/usage_history')
@login_required
def proxy_usage_history(proxy_id):
    granularity = (request.args.get("granularity") or "daily").strip().lower()
    if granularity not in ("hourly", "daily", "monthly"):
        granularity = "daily"
    days = request.args.get("days", default=7, type=int)
    days = max(1, min(60, days))
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    rows = ProxyStats.query.filter(
        ProxyStats.proxy_id == proxy_id,
        ProxyStats.timestamp >= start,
        ProxyStats.timestamp <= end
    ).order_by(ProxyStats.timestamp.asc()).all()
    return jsonify(_compute_usage_series(rows, granularity))

@api_bp.route('/alerts')
@login_required
def alerts():
    since_id = request.args.get("since_id", default=0, type=int)
    q = Alert.query.filter(Alert.id > since_id).order_by(Alert.id.asc()).limit(50).all()
    data = []
    for a in q:
        data.append({
            "id": a.id,
            "proxy_id": a.proxy_id,
            "severity": a.severity,
            "message": a.message,
            "created_at": a.created_at.isoformat() + "Z",
            "resolved": bool(a.resolved)
        })
    return jsonify(data)

@api_bp.route('/history')
@login_required
def history():
    try:
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)
        
        stats = db.session.query(
            func.date(ProxyStats.timestamp).label('date'),
            func.sum(ProxyStats.upload).label('total_upload'),
            func.sum(ProxyStats.download).label('total_download')
        ).filter(ProxyStats.timestamp >= start_date)\
         .group_by(func.date(ProxyStats.timestamp))\
         .all()
         
        labels = []
        upload_data = []
        download_data = []
        
        for s in stats:
            labels.append(s.date)
            upload_data.append(round(s.total_upload / (1024*1024), 2)) # MB
            download_data.append(round(s.total_download / (1024*1024), 2)) # MB
            
        if not labels:
            for i in range(7):
                d = start_date + timedelta(days=i)
                labels.append(d.strftime('%Y-%m-%d'))
                upload_data.append(0)
                download_data.append(0)
            
        return jsonify({
            "labels": labels,
            "upload": upload_data,
            "download": download_data
        })
    except Exception as e:
        print(f"History API Error: {e}")
        return jsonify({
            "labels": [],
            "upload": [],
            "download": []
        })

@api_bp.route('/activity')
@login_required
def activity():
    action = (request.args.get("action") or "").strip()
    ip = (request.args.get("ip") or "").strip()
    limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(200, limit))
    q = ActivityLog.query
    if action:
        q = q.filter(ActivityLog.action.ilike(f"%{action}%"))
    if ip:
        q = q.filter(ActivityLog.ip_address.ilike(f"%{ip}%"))
    logs = q.order_by(ActivityLog.timestamp.desc()).limit(limit).all()
    return jsonify([{
        "id": l.id,
        "action": l.action,
        "details": l.details,
        "ip_address": l.ip_address,
        "timestamp": l.timestamp.isoformat() + "Z"
    } for l in logs])
