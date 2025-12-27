import docker
import json

try:
    client = docker.from_env()
    containers = client.containers.list()
    
    print(f"Found {len(containers)} containers.")
    
    for c in containers:
        print(f"Checking container: {c.name} ({c.id[:12]})")
        stats = c.stats(stream=False)
        
        # Print network section
        networks = stats.get('networks', {})
        print(f"Networks keys: {list(networks.keys())}")
        
        total_rx = 0
        total_tx = 0
        
        for iface, data in networks.items():
            rx = data.get('rx_bytes', 0)
            tx = data.get('tx_bytes', 0)
            print(f"  Interface {iface}: RX={rx}, TX={tx}")
            total_rx += rx
            total_tx += tx
            
        print(f"Total: RX={total_rx}, TX={total_tx}")
        print("-" * 30)

except Exception as e:
    print(f"Error: {e}")
