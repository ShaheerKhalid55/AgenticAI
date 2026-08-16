import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from ..auth.security import (
    create_access_token,
    get_current_user,
    hash_password,
    password_requirement_error,
    verify_password,
)
from ..services.invitations import InvitationError

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class RegisterRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: str
    tenant_id: str
    company_name: str
    full_name: str
    email: str
    role: str


class InvitationTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=40, max_length=256)


class AcceptInvitationRequest(InvitationTokenRequest):
    password: str = Field(min_length=12, max_length=128)
    password_confirmation: str = Field(min_length=12, max_length=128)

    @model_validator(mode="after")
    def validate_passwords(self):
        if self.password != self.password_confirmation:
            raise ValueError("Passwords do not match")
        requirement_error = password_requirement_error(self.password)
        if requirement_error:
            raise ValueError(requirement_error)
        return self


def _public_user(user: dict, company: dict) -> UserResponse:
    return UserResponse(
        id=user["id"],
        tenant_id=user["tenant_id"],
        company_name=company["name"],
        full_name=user["full_name"],
        email=user["email"],
        role=user["role"],
    )


@router.post("/register")
def register(request: RegisterRequest):
    from ..main import services

    email = request.email.lower().strip()
    existing = services.mongo.users.find_one({"email": email})
    if existing:
        raise HTTPException(409, "An account with this email already exists")

    now = datetime.now(timezone.utc)
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    company = {
        "id": tenant_id,
        "name": request.company_name.strip(),
        "created_at": now,
        "status": "active",
    }
    user = {
        "id": user_id,
        "tenant_id": tenant_id,
        "full_name": request.full_name.strip(),
        "email": email,
        "password_hash": hash_password(request.password),
        "role": "company_admin",
        "status": "active",
        "created_at": now,
    }

    services.mongo.companies.insert_one(company)
    try:
        services.mongo.users.insert_one(user)
        services.mongo.get_assistant(tenant_id)
    except Exception:
        services.mongo.companies.delete_one({"id": tenant_id})
        raise

    token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        email=email,
        role=user["role"],
    )
    return {"access_token": token, "token_type": "bearer", "user": _public_user(user, company).model_dump()}


@router.post("/login")
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    from ..main import services

    email = form.username.lower().strip()
    user = services.mongo.users.find_one({"email": email})
    if not user or user.get("status") != "active" or not verify_password(form.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    company = services.mongo.companies.find_one({"id": user["tenant_id"], "status": "active"})
    if not company:
        raise HTTPException(403, "Company account is inactive")

    token = create_access_token(
        user_id=user["id"],
        tenant_id=user["tenant_id"],
        email=user["email"],
        role=user["role"],
    )
    return {"access_token": token, "token_type": "bearer", "user": _public_user(user, company).model_dump()}


def _invitation_http_error(exc: InvitationError) -> HTTPException:
    status_code = {
        "invalid": status.HTTP_400_BAD_REQUEST,
        "expired": status.HTTP_410_GONE,
        "revoked": status.HTTP_410_GONE,
        "already_used": status.HTTP_410_GONE,
    }.get(exc.code, status.HTTP_409_CONFLICT)
    return HTTPException(status_code, detail={"code": exc.code, "message": exc.message})


@router.post("/invitations/validate")
def validate_invitation(request: InvitationTokenRequest, response: Response):
    from ..main import services

    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        return services.invitations.validate(request.token)
    except InvitationError as exc:
        raise _invitation_http_error(exc) from exc


@router.post("/invitations/accept")
def accept_invitation(request: AcceptInvitationRequest, response: Response):
    from ..main import services

    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        return services.invitations.accept(request.token, request.password)
    except InvitationError as exc:
        raise _invitation_http_error(exc) from exc


@router.get("/me", response_model=UserResponse)
def me(current_user: dict = Depends(get_current_user)):
    from ..main import services

    user = services.mongo.users.find_one({"id": current_user["sub"], "tenant_id": current_user["tenant_id"]})
    company = services.mongo.companies.find_one({"id": current_user["tenant_id"]})
    if not user or not company:
        raise HTTPException(401, "User account no longer exists")
    return _public_user(user, company)
