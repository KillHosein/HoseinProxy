from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, DateTime, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class Admin(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

class ProxyNode(Base):
    __tablename__ = "proxy_nodes"
    id = Column(Integer, primary_key=True, index=True)
    port = Column(Integer, unique=True, index=True)
    tag = Column(String, nullable=True) # Ad Tag
    server_ip = Column(String) # Public IP
    container_id = Column(String, nullable=True)
    status = Column(String, default="stopped") # running, stopped
    location = Column(String, default="Unknown")
    
    users = relationship("User", back_populates="proxy_node")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    proxy_node_id = Column(Integer, ForeignKey("proxy_nodes.id"))
    
    name = Column(String, index=True)
    secret = Column(String, unique=True, index=True)
    
    # Limits
    bandwidth_limit_gb = Column(Float, default=0) # 0 means unlimited
    expiration_date = Column(DateTime, nullable=True)
    max_concurrent_users = Column(Integer, default=0)
    
    # Stats
    bytes_consumed = Column(Float, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    proxy_node = relationship("ProxyNode", back_populates="users")
    activity_logs = relationship("ActivityLog", back_populates="user")

class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    action = Column(String) # e.g., "connected", "disconnected", "bandwidth_usage"
    details = Column(String, nullable=True)
    
    user = relationship("User", back_populates="activity_logs")
