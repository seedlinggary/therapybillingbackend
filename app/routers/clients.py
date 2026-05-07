"""
Client management — therapist-side CRUD + invite flow.
"""
import secrets
from datetime import datetime, timedelta
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.core.deps import get_current_therapist, get_current_client
from app.models.therapist import Therapist
from app.models.client import Client
from app.models.therapist_client import TherapistClient
from app.schemas.client import (
    ClientCreate, ClientProfile, TherapistClientDetail,
    TherapistClientUpdate, TherapistClientBillingUpdate, ClientUpdate,
)
from app.services.email_service import send_client_invite

router = APIRouter(tags=["clients"])


def _build_detail(rel: TherapistClient, client: Client) -> TherapistClientDetail:
    return TherapistClientDetail(
        id=rel.id,
        client_id=rel.client_id,
        email=client.email,
        name=client.name,
        phone=client.phone,
        default_session_price=float(rel.default_session_price),
        is_active=rel.is_active,
        notes=rel.notes,
        client_is_active=client.is_active,
        billing_frequency=rel.billing_frequency,
        billing_anchor_day=rel.billing_anchor_day,
        created_at=rel.created_at,
    )


# ─── Therapist: manage own clients ───────────────────────────────────────────

@router.get("/therapist/clients", response_model=List[TherapistClientDetail])
def list_my_clients(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    rels = (
        db.query(TherapistClient)
        .options(joinedload(TherapistClient.client))
        .filter(TherapistClient.therapist_id == therapist.id)
        .all()
    )
    return [_build_detail(rel, rel.client) for rel in rels]


@router.post("/therapist/clients", response_model=TherapistClientDetail, status_code=201)
def create_client(
    data: ClientCreate,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    # Check if client already exists
    client = db.query(Client).filter(Client.email == data.email).first()
    if not client:
        invite_token = secrets.token_urlsafe(32)
        client = Client(
            email=data.email,
            name=data.name,
            phone=data.phone,
            is_active=False,
            invite_token=invite_token,
            invite_token_expires=datetime.utcnow() + timedelta(hours=72),
        )
        db.add(client)
        db.flush()
        send_client_invite(client.email, client.name, therapist.name, invite_token)
    else:
        # Client already has account — just link
        existing_rel = db.query(TherapistClient).filter(
            TherapistClient.therapist_id == therapist.id,
            TherapistClient.client_id == client.id,
        ).first()
        if existing_rel:
            raise HTTPException(status_code=409, detail="Client already linked to this therapist")

    rel = TherapistClient(
        therapist_id=therapist.id,
        client_id=client.id,
        default_session_price=data.default_session_price,
        notes=data.notes,
        billing_frequency=therapist.default_billing_frequency or "same_day",
        billing_anchor_day=therapist.default_billing_anchor_day,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)
    db.refresh(client)
    return _build_detail(rel, client)


@router.get("/therapist/clients/{client_id}", response_model=TherapistClientDetail)
def get_client(
    client_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    rel = _get_relationship_or_404(db, therapist.id, client_id)
    return _build_detail(rel, rel.client)


@router.patch("/therapist/clients/{client_id}", response_model=TherapistClientDetail)
def update_client(
    client_id: str,
    data: TherapistClientUpdate,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    rel = _get_relationship_or_404(db, therapist.id, client_id)
    client = rel.client

    # Split fields: some go to the Client record, rest go to the relationship
    client_fields = {"name", "email", "phone"}
    patch = data.model_dump(exclude_none=True)

    if "email" in patch and patch["email"] != client.email:
        clash = db.query(Client).filter(Client.email == patch["email"], Client.id != client.id).first()
        if clash:
            raise HTTPException(status_code=409, detail="That email is already used by another client")

    for field, value in patch.items():
        if field in client_fields:
            setattr(client, field, value)
        else:
            setattr(rel, field, value)

    db.commit()
    db.refresh(rel)
    db.refresh(client)
    return _build_detail(rel, client)


@router.patch("/therapist/clients/{client_id}/billing", response_model=TherapistClientDetail)
def update_client_billing(
    client_id: str,
    data: TherapistClientBillingUpdate,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    rel = _get_relationship_or_404(db, therapist.id, client_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(rel, field, value)
    db.commit()
    db.refresh(rel)
    client = rel.client
    return _build_detail(rel, client)


@router.post("/therapist/clients/{client_id}/resend-invite", status_code=200)
def resend_invite(
    client_id: str,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_db),
):
    rel = _get_relationship_or_404(db, therapist.id, client_id)
    client = rel.client
    if client.is_active:
        raise HTTPException(status_code=400, detail="Client already has an active account")

    invite_token = secrets.token_urlsafe(32)
    client.invite_token = invite_token
    client.invite_token_expires = datetime.utcnow() + timedelta(hours=72)
    db.commit()

    send_client_invite(client.email, client.name, therapist.name, invite_token)
    return {"message": "Invite resent"}


# ─── Client: view own profile ─────────────────────────────────────────────────

@router.get("/client/me", response_model=ClientProfile)
def get_my_profile(client: Client = Depends(get_current_client)):
    return client


@router.patch("/client/me", response_model=ClientProfile)
def update_my_profile(
    data: ClientUpdate,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(client, field, value)
    db.commit()
    db.refresh(client)
    return client


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_relationship_or_404(db: Session, therapist_id, client_id: str) -> TherapistClient:
    rel = (
        db.query(TherapistClient)
        .options(joinedload(TherapistClient.client))
        .filter(
            TherapistClient.therapist_id == therapist_id,
            TherapistClient.client_id == client_id,
        )
        .first()
    )
    if not rel:
        raise HTTPException(status_code=404, detail="Client not found or not linked to this therapist")
    return rel
