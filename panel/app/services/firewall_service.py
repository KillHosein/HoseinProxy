import sys
import subprocess
from app.models import BlockedIP
from app.extensions import db

def _apply_firewall_rule(ip, action='block'):
    """Applies iptables rule for a specific IP"""
    if not sys.platform.startswith('linux'):
        return
        
    try:
        # Check if iptables exists
        if subprocess.call("which iptables", shell=True, stdout=subprocess.DEVNULL) != 0:
            # print("iptables not found, skipping firewall rule")
            return

        # Check if rule exists
        check_cmd = f"iptables -C INPUT -s {ip} -j DROP"
        rule_exists = subprocess.call(check_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
        
        if action == 'block':
            if not rule_exists:
                # Add DROP rule to INPUT and FORWARD chains
                subprocess.check_call(f"iptables -I INPUT -s {ip} -j DROP", shell=True)
                subprocess.check_call(f"iptables -I FORWARD -s {ip} -j DROP", shell=True)
        elif action == 'unblock':
            if rule_exists:
                # Remove rule
                try:
                    subprocess.check_call(f"iptables -D INPUT -s {ip} -j DROP", shell=True)
                    subprocess.check_call(f"iptables -D FORWARD -s {ip} -j DROP", shell=True)
                except:
                    pass
    except Exception as e:
        print(f"Firewall Error ({action} {ip}): {e}")

def _sync_firewall():
    """Syncs DB blocked IPs with iptables on startup"""
    if not sys.platform.startswith('linux'):
        return
    try:
        blocked = BlockedIP.query.all()
        for b in blocked:
            _apply_firewall_rule(b.ip_address, 'block')
    except:
        pass
