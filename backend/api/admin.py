import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from ..auth.security import require_role, hash_password

router = APIRouter(prefix="/api/admin", tags=["administration"])


class CreateUserRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="employee", pattern="^(employee|company_admin)$")


@router.get("/users")
def list_users(current_user: dict = Depends(require_role("company_admin"))):
    from ..main import services
    users = services.mongo.users.find(
        {"tenant_id": current_user["tenant_id"]},
        {"_id": 0, "password_hash": 0},
    )
    return list(users)


@router.post("/users")
def create_user(request: CreateUserRequest, current_user: dict = Depends(require_role("company_admin"))):
    from ..main import services
    email = request.email.lower().strip()
    if services.mongo.users.find_one({"email": email}):
        raise HTTPException(409, "An account with this email already exists")

    now = datetime.now(timezone.utc)
    user = {
        "id": str(uuid.uuid4()),
        "tenant_id": current_user["tenant_id"],
        "full_name": request.full_name.strip(),
        "email": email,
        "password_hash": hash_password(request.password),
        "role": request.role,
        "status": "active",
        "created_at": now,
    }
    services.mongo.users.insert_one(user)
    user.pop("password_hash", None)
    user.pop("_id", None)
    return user
