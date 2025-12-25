import docker
import sys

try:
    client = docker.from_env()
    print("Docker connected.")
    
    # Try to find container by name or port
    containers = client.containers.list(all=True)
    target = None
    
    print("Scanning containers...")
    for c in containers:
        print(f"- {c.name} ({c.status})")
        if '2083' in c.name or 'mtproto_2083' in c.name:
            target = c
            
    if target:
        print(f"\nTarget found: {target.name}")
        print("Logs:")
        print(target.logs().decode('utf-8', errors='ignore'))
    else:
        print("\nContainer for port 2083 not found.")
        
except Exception as e:
    print(f"Error: {e}")
