import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pymongo.errors import DuplicateKeyError

from ..auth.security import require_role
from ..config import INVITATION_RESEND_COOLDOWN_SECONDS
from ..services.invitations import InvitationError

router = APIRouter(prefix="/api/admin", tags=["administration"])


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    role: str = Field(default="employee", pattern="^(employee|company_admin)$")


def _public_user(user: dict, invitation: dict | None = None) -> dict:
    result = {
        key: value
        for key, value in user.items()
        if key not in {"_id", "password_hash"}
    }
    result["status"] = result.get("status", "active")
    if invitation is not None:
        result["invitation"] = invitation
    return result


@router.get("/users")
def list_users(current_user: dict = Depends(require_role("company_admin"))):
    from ..main import services

    users = list(services.mongo.users.find(
        {"tenant_id": current_user["tenant_id"]},
        {"_id": 0, "password_hash": 0},
    ))
    results = []
    for user in users:
        invitation = services.invitations.public_summary(
            services.invitations.latest_for_user(current_user["tenant_id"], user["id"])
        )
        results.append(_public_user(user, invitation))
    return results


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    request: CreateUserRequest,
    current_user: dict = Depends(require_role("company_admin")),
):
    from ..main import services

    email = request.email.lower().strip()
    existing = services.mongo.users.find_one({"email": email})
    if existing:
        if existing.get("tenant_id") == current_user["tenant_id"]:
            raise HTTPException(
                409,
                "A user with this email already exists in this workspace. Resend their invitation if needed.",
            )
        raise HTTPException(409, "An account with this email cannot be added")

    company = services.mongo.companies.find_one({
        "id": current_user["tenant_id"], "status": "active"
    })
    if not company:
        raise HTTPException(409, "Workspace is not active")

    now = datetime.now(timezone.utc)
    user = {
        "id": str(uuid.uuid4()),
        "tenant_id": current_user["tenant_id"],
        "full_name": request.full_name.strip(),
        "email": email,
        "role": request.role,
        "status": "invited",
        "created_at": now,
        "updated_at": now,
        "invited_at": now,
        "invited_by": current_user["sub"],
    }
    try:
        services.mongo.users.insert_one(user)
    except DuplicateKeyError as exc:
        raise HTTPException(409, "An account with this email cannot be added") from exc

    invitation, delivered = services.invitations.create(
        user=user,
        company=company,
        actor_id=current_user["sub"],
    )
    result = _public_user(
        user,
        services.invitations.public_summary(invitation),
    )
    result["email_delivered"] = delivered
    return result


@router.post("/users/{user_id}/resend-invitation")
def resend_invitation(
    user_id: str,
    current_user: dict = Depends(require_role("company_admin")),
):
    from ..main import services

    tenant_id = current_user["tenant_id"]
    user = services.mongo.users.find_one({"id": user_id, "tenant_id": tenant_id})
    if not user:
        raise HTTPException(404, "User not found")
    if user.get("status") != "invited":
        raise HTTPException(409, "Only invited users can receive another invitation")

    latest = services.invitations.latest_for_user(tenant_id, user_id)
    if latest and latest.get("last_delivery_attempt_at"):
        last_attempt = latest["last_delivery_attempt_at"]
        if last_attempt.tzinfo is None:
            last_attempt = last_attempt.replace(tzinfo=timezone.utc)
        seconds = (datetime.now(timezone.utc) - last_attempt).total_seconds()
        if seconds < INVITATION_RESEND_COOLDOWN_SECONDS:
            remaining = max(1, int(INVITATION_RESEND_COOLDOWN_SECONDS - seconds + 0.999))
            raise HTTPException(
                429,
                f"Please wait {remaining} seconds before resending this invitation",
                headers={"Retry-After": str(remaining)},
            )

    company = services.mongo.companies.find_one({"id": tenant_id, "status": "active"})
    if not company:
        raise HTTPException(409, "Workspace is not active")
    invitation, delivered = services.invitations.create(
        user=user,
        company=company,
        actor_id=current_user["sub"],
        resend_count=int((latest or {}).get("resend_count", 0)) + 1,
    )
    services.mongo.users.update_one(
        {"id": user_id, "tenant_id": tenant_id},
        {"$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    return {
        "id": user_id,
        "status": "invited",
        "email_delivered": delivered,
        "invitation": services.invitations.public_summary(invitation),
    }


@router.post("/users/{user_id}/revoke-invitation")
def revoke_invitation(
    user_id: str,
    current_user: dict = Depends(require_role("company_admin")),
):
    from ..main import services

    tenant_id = current_user["tenant_id"]
    user = services.mongo.users.find_one({"id": user_id, "tenant_id": tenant_id})
    if not user:
        raise HTTPException(404, "User not found")
    if user.get("status") != "invited":
        raise HTTPException(409, "Only invited users can have an invitation revoked")
    try:
        invitation = services.invitations.revoke(
            tenant_id=tenant_id,
            user_id=user_id,
            actor_id=current_user["sub"],
        )
    except InvitationError as exc:
        raise HTTPException(409, exc.message) from exc
    return {
        "id": user_id,
        "status": "invited",
        "invitation": services.invitations.public_summary(invitation),
    }


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
    policy_documents = services.mongo.documents.count_documents({"tenant_id": tenant_id})
    active_documents = services.mongo.documents.count_documents({"tenant_id": tenant_id, "status": "active"})
    archived_documents = services.mongo.documents.count_documents({"tenant_id": tenant_id, "status": "archived"})
    failed_documents = services.mongo.documents.count_documents({"tenant_id": tenant_id, "status": "failed"})

    policy_chunks = 0
    try:
        from ..config import POLICY_COLLECTION
        if services.qdrant.client.collection_exists(POLICY_COLLECTION):
            policy_chunks = services.qdrant.client.count(
                collection_name=POLICY_COLLECTION,
                count_filter=services.qdrant._active_policy_filter(tenant_id),
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
        "policy_documents": policy_documents,
        "knowledge_chunks": policy_chunks,
        "knowledge_documents": policy_documents,
        "active_documents": active_documents,
        "archived_documents": archived_documents,
        "failed_documents": failed_documents,
    }


@router.patch("/users/{user_id}/status")
def update_user_status(
    user_id: str,
    current_user: dict = Depends(require_role("company_admin")),
):
    from ..main import services

    if user_id == current_user["sub"]:
        raise HTTPException(400, "You cannot disable your own account")
    tenant_id = current_user["tenant_id"]
    user = services.mongo.users.find_one({"id": user_id, "tenant_id": tenant_id})
    if not user:
        raise HTTPException(404, "User not found")
    current_status = user.get("status", "active")
    if current_status == "invited":
        raise HTTPException(409, "Invited users must accept an invitation before they can be enabled")
    if current_status not in {"active", "inactive"}:
        raise HTTPException(409, "This user status cannot be changed")
    if current_status == "inactive" and not user.get("password_hash"):
        raise HTTPException(409, "This account has no password and cannot be enabled")

    new_status = "inactive" if current_status == "active" else "active"
    now = datetime.now(timezone.utc)
    audit_fields = (
        {"disabled_at": now, "disabled_by": current_user["sub"]}
        if new_status == "inactive"
        else {"enabled_at": now, "enabled_by": current_user["sub"]}
    )
    services.mongo.users.update_one(
        {"id": user_id, "tenant_id": tenant_id, "status": current_status},
        {"$set": {"status": new_status, "updated_at": now, **audit_fields}},
    )
    return {"id": user_id, "status": new_status}
