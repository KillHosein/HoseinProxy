import docker

try:
    client = docker.from_env()
except Exception as e:
    print(f"Warning: Docker connection failed. {e}")
    client = None
