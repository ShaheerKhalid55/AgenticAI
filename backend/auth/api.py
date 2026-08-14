import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field

from ..auth.security import create_access_token, get_current_user, hash_password, verify_password

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


@router.get("/me", response_model=UserResponse)
def me(current_user: dict = Depends(get_current_user)):
    from ..main import services

    user = services.mongo.users.find_one({"id": current_user["sub"], "tenant_id": current_user["tenant_id"]})
    company = services.mongo.companies.find_one({"id": current_user["tenant_id"]})
    if not user or not company:
        raise HTTPException(401, "User account no longer exists")
    return _public_user(user, company)
