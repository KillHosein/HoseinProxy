import docker

try:
    client = docker.from_env()
    print("Docker client connected.")
    
    containers = client.containers.list(all=True)
    print(f"Found {len(containers)} containers.")
    
    for c in containers:
        if 'mtproto' in c.name:
            print(f"\n--- Container: {c.name} ({c.status}) ---")
            print(f"Image: {c.image.tags}")
            try:
                logs = c.logs(tail=20).decode('utf-8', errors='ignore')
                print("Logs:")
                print(logs)
            except Exception as e:
                print(f"Error getting logs: {e}")
                
except Exception as e:
    print(f"Error: {e}")
