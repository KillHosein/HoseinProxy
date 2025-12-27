from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import secrets
from fastapi.middleware.cors import CORSMiddleware

from . import models, schemas, database
from .services import docker_service

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="HoseinProxy Manager")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/proxies/", response_model=schemas.ProxyNode)
def create_proxy(proxy: schemas.ProxyNodeCreate, db: Session = Depends(get_db)):
    db_proxy = models.ProxyNode(**proxy.dict(), status="stopped")
    db.add(db_proxy)
    db.commit()
    db.refresh(db_proxy)
    return db_proxy

@app.get("/proxies/", response_model=List[schemas.ProxyNode])
def read_proxies(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    proxies = db.query(models.ProxyNode).offset(skip).limit(limit).all()
    return proxies

@app.post("/proxies/{proxy_id}/start")
def start_proxy(proxy_id: int, db: Session = Depends(get_db)):
    proxy = db.query(models.ProxyNode).filter(models.ProxyNode.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    
    # Get all active users' secrets
    users = db.query(models.User).filter(models.User.proxy_node_id == proxy_id, models.User.is_active == True).all()
    secret_list = [u.secret for u in users]
    
    # If no users, maybe create a default one or just start (some proxies require at least one secret)
    if not secret_list:
        # Auto-create a default user/secret if none exists?
        # Or just fail? Let's warn.
        pass

    try:
        container_id = docker_service.start_proxy_container(proxy.port, secret_list, proxy.tag)
        proxy.container_id = container_id
        proxy.status = "running"
        db.commit()
        return {"status": "started", "container_id": container_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/proxies/{proxy_id}/stop")
def stop_proxy(proxy_id: int, db: Session = Depends(get_db)):
    proxy = db.query(models.ProxyNode).filter(models.ProxyNode.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
        
    docker_service.stop_proxy_container(proxy.port)
    proxy.status = "stopped"
    proxy.container_id = None
    db.commit()
    return {"status": "stopped"}

@app.post("/proxies/{proxy_id}/users/", response_model=schemas.User)
def create_user_for_proxy(proxy_id: int, user: schemas.UserCreate, db: Session = Depends(get_db)):
    proxy = db.query(models.ProxyNode).filter(models.ProxyNode.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    
    # Generate random secret
    new_secret = secrets.token_hex(16)
    
    db_user = models.User(**user.dict(), secret=new_secret, proxy_node_id=proxy_id)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    # If proxy is running, restart it to apply new secret
    if proxy.status == "running":
        start_proxy(proxy_id, db)
        
    return db_user

@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    proxy_id = user.proxy_node_id
    db.delete(user)
    db.commit()
    
    # Restart proxy
    proxy = db.query(models.ProxyNode).filter(models.ProxyNode.id == proxy_id).first()
    if proxy and proxy.status == "running":
        start_proxy(proxy_id, db)
        
    return {"status": "deleted"}

@app.get("/stats")
def get_global_stats(db: Session = Depends(get_db)):
    total_proxies = db.query(models.ProxyNode).count()
    total_users = db.query(models.User).count()
    active_proxies = db.query(models.ProxyNode).filter(models.ProxyNode.status == "running").count()
    return {
        "total_proxies": total_proxies,
        "active_proxies": active_proxies,
        "total_users": total_users
    }
