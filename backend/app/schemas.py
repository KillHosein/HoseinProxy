from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class UserBase(BaseModel):
    name: str
    bandwidth_limit_gb: Optional[float] = 0
    expiration_date: Optional[datetime] = None

class UserCreate(UserBase):
    pass

class User(UserBase):
    id: int
    secret: str
    proxy_node_id: int
    bytes_consumed: float
    is_active: bool
    created_at: datetime
    
    class Config:
        orm_mode = True

class ProxyNodeBase(BaseModel):
    port: int
    tag: Optional[str] = None
    server_ip: str

class ProxyNodeCreate(ProxyNodeBase):
    pass

class ProxyNode(ProxyNodeBase):
    id: int
    status: str
    container_id: Optional[str]
    users: List[User] = []

    class Config:
        orm_mode = True
