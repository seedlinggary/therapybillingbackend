from pydantic import BaseModel
from typing import Optional
import uuid


class ServiceTypeCreate(BaseModel):
    name: str
    duration_minutes: int = 50


class ServiceTypeUpdate(BaseModel):
    name: Optional[str] = None
    duration_minutes: Optional[int] = None
    is_active: Optional[bool] = None


class ServiceTypeResponse(BaseModel):
    id: uuid.UUID
    name: str
    duration_minutes: int
    is_active: bool

    class Config:
        from_attributes = True
