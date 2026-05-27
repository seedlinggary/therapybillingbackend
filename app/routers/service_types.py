from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid

from app.database import get_db
from app.models.service_type import ServiceType
from app.schemas.service_type import ServiceTypeCreate, ServiceTypeUpdate, ServiceTypeResponse
from app.core.deps import get_current_therapist

router = APIRouter(prefix="/therapist/service-types", tags=["service-types"])


@router.get("", response_model=List[ServiceTypeResponse])
def list_service_types(
    db: Session = Depends(get_db),
    therapist=Depends(get_current_therapist),
):
    return (
        db.query(ServiceType)
        .filter(ServiceType.therapist_id == therapist.id, ServiceType.is_active == True)
        .order_by(ServiceType.created_at)
        .all()
    )


@router.post("", response_model=ServiceTypeResponse, status_code=201)
def create_service_type(
    data: ServiceTypeCreate,
    db: Session = Depends(get_db),
    therapist=Depends(get_current_therapist),
):
    svc = ServiceType(
        therapist_id=therapist.id,
        name=data.name,
        duration_minutes=data.duration_minutes,
    )
    db.add(svc)
    db.commit()
    db.refresh(svc)
    return svc


@router.put("/{service_id}", response_model=ServiceTypeResponse)
def update_service_type(
    service_id: uuid.UUID,
    data: ServiceTypeUpdate,
    db: Session = Depends(get_db),
    therapist=Depends(get_current_therapist),
):
    svc = db.query(ServiceType).filter(
        ServiceType.id == service_id,
        ServiceType.therapist_id == therapist.id,
    ).first()
    if not svc:
        raise HTTPException(status_code=404, detail="Service type not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(svc, field, value)
    db.commit()
    db.refresh(svc)
    return svc


@router.delete("/{service_id}", status_code=204)
def delete_service_type(
    service_id: uuid.UUID,
    db: Session = Depends(get_db),
    therapist=Depends(get_current_therapist),
):
    svc = db.query(ServiceType).filter(
        ServiceType.id == service_id,
        ServiceType.therapist_id == therapist.id,
    ).first()
    if not svc:
        raise HTTPException(status_code=404, detail="Service type not found")
    svc.is_active = False
    db.commit()
