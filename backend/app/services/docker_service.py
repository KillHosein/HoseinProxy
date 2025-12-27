import docker
import logging
from typing import List

client = docker.from_env()

IMAGE_NAME = "telegrammessenger/proxy:latest"

def ensure_image():
    try:
        client.images.get(IMAGE_NAME)
    except docker.errors.ImageNotFound:
        logging.info(f"Pulling {IMAGE_NAME}...")
        client.images.pull(IMAGE_NAME)

def start_proxy_container(proxy_port: int, secrets: List[str], tag: str = None) -> str:
    """
    Starts a proxy container on the host port `proxy_port`.
    Inside the container, it listens on 443.
    Returns the container ID.
    """
    ensure_image()
    
    container_name = f"mtproto_proxy_{proxy_port}"
    
    # Construct command arguments
    # The official image entrypoint usually handles env vars, but for multi-secret we might need to override cmd.
    # However, to be safe and use the image's built-in logic, we can try to pass 'SECRET' as a comma separated list if supported, 
    # OR (better) use the python command directly if we know the path.
    # The official image usually runs /run.sh. 
    # Let's try to just pass environment variables for the simple case, 
    # but for multi-user, we likely need to construct the command.
    
    # Actually, the official run.sh supports 'SECRET' env var. 
    # If we want multiple secrets, we can pass them in the command.
    # Entrypoint is often /bin/sh /run.sh
    
    # Strategy: We will mount a config or just pass arguments to the binary.
    # Let's use the environment variable 'SECRET' for the first user, and if we need more, we might face issues with the default run.sh.
    # Alternative: Use a different image 'alexbers/mtprotoproxy' which is more feature rich for this.
    # BUT, the user prompt implies "Advanced", so we should support multiple users.
    
    # Let's use `alexbers/mtprotoproxy` logic? No, let's stick to official but override command.
    # Command: python3 mtprotoproxy.py -p 443 -H 443 -S <s1> -S <s2> ...
    
    cmd_args = ["python3", "mtprotoproxy.py", "-p", "443", "-H", "443"]
    for s in secrets:
        cmd_args.extend(["-S", s])
        
    if tag:
        cmd_args.extend(["-P", tag]) # -P is usually for Tag in some variants, or --tag
        # Official repo uses --tag? No, official repo uses -P for ad tag.
    
    # We also need to set WORKERS.
    cmd_args.extend(["--workers", "2"])
    
    # Enable Stats
    cmd_args.extend(["--http-stats-port", "8888"])
    stats_port = proxy_port + 10000

    try:
        # Check if exists and remove
        try:
            old = client.containers.get(container_name)
            old.remove(force=True)
        except docker.errors.NotFound:
            pass

        container = client.containers.run(
            IMAGE_NAME,
            command=cmd_args,
            ports={
                '443/tcp': proxy_port,
                '8888/tcp': stats_port
            },
            name=container_name,
            detach=True,
            restart_policy={"Name": "always"}
        )
        return container.id
    except Exception as e:
        logging.error(f"Failed to start container: {e}")
        raise e

def stop_proxy_container(proxy_port: int):
    container_name = f"mtproto_proxy_{proxy_port}"
    try:
        container = client.containers.get(container_name)
        container.stop()
        container.remove()
    except docker.errors.NotFound:
        pass

def get_container_stats(proxy_port: int):
    container_name = f"mtproto_proxy_{proxy_port}"
    try:
        container = client.containers.get(container_name)
        return container.stats(stream=False)
    except:
        return None

import requests
def fetch_proxy_internal_stats(proxy_port: int):
    stats_port = proxy_port + 10000
    try:
        resp = requests.get(f"http://localhost:{stats_port}/stats", timeout=2)
        if resp.status_code == 200:
            return resp.text
    except:
        pass
    return None
