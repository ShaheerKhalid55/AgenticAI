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


@router.get("/overview")
def admin_overview(current_user: dict = Depends(require_role("company_admin"))):
    from ..main import services

    tenant_id = current_user["tenant_id"]
    user_filter = {"tenant_id": tenant_id}
    total_users = services.mongo.users.count_documents(user_filter)
    active_users = services.mongo.users.count_documents({**user_filter, "status": "active"})
    admins = services.mongo.users.count_documents({**user_filter, "role": "company_admin"})
    employees = services.mongo.users.count_documents({**user_filter, "role": "employee"})
    conversations = services.mongo.sessions.count_documents({"tenant_id": tenant_id})

    policy_chunks = 0
    try:
        if services.qdrant.client.collection_exists(services.qdrant.POLICY_COLLECTION if hasattr(services.qdrant, "POLICY_COLLECTION") else ""):
            pass
    except Exception:
        pass
    try:
        from ..config import POLICY_COLLECTION
        if services.qdrant.client.collection_exists(POLICY_COLLECTION):
            policy_chunks = services.qdrant.client.count(
                collection_name=POLICY_COLLECTION,
                count_filter=services.qdrant._tenant_filter(tenant_id),
                exact=True,
            ).count
    except Exception:
        policy_chunks = 0

    company = services.mongo.companies.find_one({"id": tenant_id}, {"_id": 0, "name": 1, "status": 1, "created_at": 1}) or {}
    return {
        "company": company,
        "users": total_users,
        "active_users": active_users,
        "admins": admins,
        "employees": employees,
        "conversations": conversations,
        "policy_chunks": policy_chunks,
    }


@router.patch("/users/{user_id}/status")
def update_user_status(user_id: str, current_user: dict = Depends(require_role("company_admin"))):
    from ..main import services

    if user_id == current_user["sub"]:
        raise HTTPException(400, "You cannot disable your own account")
    user = services.mongo.users.find_one({"id": user_id, "tenant_id": current_user["tenant_id"]})
    if not user:
        raise HTTPException(404, "User not found")
    new_status = "inactive" if user.get("status", "active") == "active" else "active"
    services.mongo.users.update_one({"id": user_id, "tenant_id": current_user["tenant_id"]}, {"$set": {"status": new_status}})
    return {"id": user_id, "status": new_status}
