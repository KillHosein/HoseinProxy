import sys
import os

# Add current directory to path so we can import app
sys.path.append(os.getcwd())

try:
    print("Importing app.models...")
    from app.models import Proxy
    print("Importing app.utils.helpers...")
    from app.utils.helpers import format_mtproxy_client_secret
    
    print("Creating dummy proxy...")
    p = Proxy(secret="0"*32, proxy_type="tls", tls_domain="google.com")
    
    print("Testing display_secret...")
    print(f"Secret: {p.display_secret}")
    
    print("SUCCESS")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
