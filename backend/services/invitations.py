import hashlib
import html
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from pymongo import ReturnDocument

from ..auth.security import hash_password
from ..config import APP_BASE_URL, INVITATION_EXPIRY_HOURS
from .email import EmailMessage, TransactionalEmailService


OPEN_INVITATION_STATUSES = ["pending_delivery", "sent", "delivery_failed"]


class InvitationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class InvitationService:
    def __init__(self, mongo, email: TransactionalEmailService):
        self.mongo = mongo
        self.email = email

    def _audit(
        self,
        event: str,
        invitation: dict,
        *,
        actor_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.mongo.invitation_audit.insert_one({
            "id": str(uuid.uuid4()),
            "event": event,
            "invitation_id": invitation["id"],
            "tenant_id": invitation["tenant_id"],
            "user_id": invitation["user_id"],
            "actor_id": actor_id,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc),
        })

    @staticmethod
    def public_summary(invitation: dict | None) -> dict | None:
        if not invitation:
            return None
        return {
            key: invitation.get(key)
            for key in (
                "id",
                "status",
                "created_at",
                "expires_at",
                "sent_at",
                "accepted_at",
                "revoked_at",
                "last_delivery_attempt_at",
                "delivery_attempts",
                "resend_count",
                "provider",
                "provider_message_id",
                "delivery_error",
            )
        }

    def latest_for_user(self, tenant_id: str, user_id: str) -> dict | None:
        return self.mongo.invitations.find_one(
            {"tenant_id": tenant_id, "user_id": user_id},
            sort=[("created_at", -1)],
        )

    def _revoke_open(self, tenant_id: str, user_id: str, actor_id: str) -> int:
        now = datetime.now(timezone.utc)
        open_invitations = list(self.mongo.invitations.find({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "status": {"$in": OPEN_INVITATION_STATUSES},
        }))
        if not open_invitations:
            return 0
        ids = [item["id"] for item in open_invitations]
        self.mongo.invitations.update_many(
            {"id": {"$in": ids}, "status": {"$in": OPEN_INVITATION_STATUSES}},
            {"$set": {
                "status": "revoked",
                "revoked_at": now,
                "revoked_by": actor_id,
                "updated_at": now,
            }},
        )
        for invitation in open_invitations:
            self._audit("invitation_revoked", invitation, actor_id=actor_id)
        return len(ids)

    @staticmethod
    def _message(user: dict, company: dict, invitation_url: str) -> EmailMessage:
        recipient = html.escape(user["full_name"])
        workspace = html.escape(company["name"])
        safe_url = html.escape(invitation_url, quote=True)
        subject = f"You’re invited to join {company['name']} on Nexa"
        html_body = f"""<!doctype html>
<html><body style="font-family:Arial,sans-serif;color:#17202a;line-height:1.5">
<div style="max-width:560px;margin:0 auto;padding:28px">
<p style="font-size:22px;font-weight:700;margin:0 0 22px">Nexa</p>
<p>Hello {recipient},</p>
<p>You have been invited to join <strong>{workspace}</strong> as a workspace user on Nexa.</p>
<p style="margin:28px 0"><a href="{safe_url}" style="background:#3157d5;color:#fff;text-decoration:none;padding:12px 18px;border-radius:6px;display:inline-block">Accept Invitation</a></p>
<p>This invitation expires in {INVITATION_EXPIRY_HOURS} hours.</p>
<p style="font-size:13px;color:#5f6b7a">Security note: this invitation link is intended only for {html.escape(user['email'])}. Do not forward or share it. If you were not expecting this invitation, you can ignore this email.</p>
</div></body></html>"""
        text_body = (
            f"Hello {user['full_name']},\n\n"
            f"You have been invited to join {company['name']} as a workspace user on Nexa.\n\n"
            f"Accept invitation: {invitation_url}\n\n"
            f"This invitation expires in {INVITATION_EXPIRY_HOURS} hours. "
            f"This link is intended only for {user['email']}; do not forward or share it."
        )
        return EmailMessage(
            to=user["email"], subject=subject, html=html_body, text=text_body
        )

    def create(
        self,
        *,
        user: dict,
        company: dict,
        actor_id: str,
        resend_count: int = 0,
    ) -> tuple[dict, bool]:
        self._revoke_open(user["tenant_id"], user["id"], actor_id)
        raw_token = secrets.token_urlsafe(48)
        now = datetime.now(timezone.utc)
        invitation = {
            "id": str(uuid.uuid4()),
            "tenant_id": user["tenant_id"],
            "user_id": user["id"],
            "email": user["email"],
            "token_hash": token_hash(raw_token),
            "status": "pending_delivery",
            "created_at": now,
            "updated_at": now,
            "expires_at": now + timedelta(hours=INVITATION_EXPIRY_HOURS),
            "invited_by": actor_id,
            "delivery_attempts": 0,
            "resend_count": resend_count,
        }
        self.mongo.invitations.insert_one(invitation)
        self._audit("invitation_created", invitation, actor_id=actor_id)

        invitation_url = (
            f"{APP_BASE_URL}/accept-invitation.html#token={quote(raw_token, safe='')}"
        )
        delivery = self.email.send(self._message(user, company, invitation_url))
        attempted_at = datetime.now(timezone.utc)
        updates = {
            "status": "sent" if delivery.delivered else "delivery_failed",
            "updated_at": attempted_at,
            "last_delivery_attempt_at": attempted_at,
            "delivery_attempts": 1,
            "provider": delivery.provider,
            "provider_message_id": delivery.message_id,
            "delivery_error": delivery.error,
        }
        if delivery.delivered:
            updates["sent_at"] = attempted_at
        self.mongo.invitations.update_one({"id": invitation["id"]}, {"$set": updates})
        invitation.update(updates)
        self._audit(
            "invitation_delivered" if delivery.delivered else "invitation_delivery_failed",
            invitation,
            actor_id=actor_id,
            metadata={"provider": delivery.provider, "message_id": delivery.message_id},
        )
        return invitation, delivery.delivered

    def revoke(self, *, tenant_id: str, user_id: str, actor_id: str) -> dict:
        latest = self.latest_for_user(tenant_id, user_id)
        if not latest or latest.get("status") not in OPEN_INVITATION_STATUSES:
            raise InvitationError("not_revocable", "There is no active invitation to revoke")
        self._revoke_open(tenant_id, user_id, actor_id)
        return self.mongo.invitations.find_one({"id": latest["id"]})

    def _resolve(self, raw_token: str) -> tuple[dict, dict, dict]:
        invitation = self.mongo.invitations.find_one({"token_hash": token_hash(raw_token)})
        if not invitation:
            raise InvitationError("invalid", "This invitation link is invalid")
        now = datetime.now(timezone.utc)
        status = invitation.get("status")
        if status == "accepted":
            raise InvitationError("already_used", "This invitation has already been accepted")
        if status == "revoked":
            raise InvitationError("revoked", "This invitation has been revoked")
        if status == "expired" or _utc(invitation["expires_at"]) <= now:
            if status != "expired":
                updated = self.mongo.invitations.update_one(
                    {"id": invitation["id"], "status": {"$in": OPEN_INVITATION_STATUSES}},
                    {"$set": {"status": "expired", "updated_at": now}},
                )
                if updated.modified_count:
                    self._audit("invitation_expired", invitation)
            raise InvitationError("expired", "This invitation has expired")
        if status != "sent":
            raise InvitationError("invalid", "This invitation is not available for acceptance")
        user = self.mongo.users.find_one({
            "id": invitation["user_id"],
            "tenant_id": invitation["tenant_id"],
            "email": invitation["email"],
            "status": "invited",
        })
        company = self.mongo.companies.find_one({
            "id": invitation["tenant_id"], "status": "active"
        })
        if not user or not company:
            raise InvitationError("invalid", "This invitation is no longer valid")
        return invitation, user, company

    def validate(self, raw_token: str) -> dict:
        invitation, user, company = self._resolve(raw_token)
        local, _, domain = user["email"].partition("@")
        masked_email = f"{local[:1]}***@{domain}" if domain else "***"
        return {
            "valid": True,
            "workspace_name": company["name"],
            "recipient_name": user["full_name"],
            "email": masked_email,
            "expires_at": invitation["expires_at"],
        }

    def accept(self, raw_token: str, password: str) -> dict:
        invitation, user, company = self._resolve(raw_token)
        now = datetime.now(timezone.utc)
        claimed = self.mongo.invitations.find_one_and_update(
            {
                "id": invitation["id"],
                "status": "sent",
                "expires_at": {"$gt": now},
            },
            {"$set": {"status": "accepting", "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if not claimed:
            raise InvitationError("already_used", "This invitation is no longer available")
        password_digest = None
        activated_user = False
        try:
            password_digest = hash_password(password)
            activated = self.mongo.users.update_one(
                {
                    "id": user["id"],
                    "tenant_id": invitation["tenant_id"],
                    "email": invitation["email"],
                    "status": "invited",
                },
                {"$set": {
                    "password_hash": password_digest,
                    "status": "active",
                    "activated_at": now,
                    "updated_at": now,
                }},
            )
            if activated.modified_count != 1:
                raise InvitationError("invalid", "This invitation is no longer valid")
            activated_user = True
            accepted = self.mongo.invitations.update_one(
                {"id": invitation["id"], "status": "accepting"},
                {"$set": {
                    "status": "accepted",
                    "accepted_at": now,
                    "updated_at": now,
                }},
            )
            if accepted.modified_count != 1:
                raise RuntimeError("Invitation acceptance could not be finalized")
            invitation["status"] = "accepted"
        except Exception:
            if activated_user and password_digest:
                self.mongo.users.update_one(
                    {
                        "id": user["id"],
                        "tenant_id": invitation["tenant_id"],
                        "status": "active",
                        "password_hash": password_digest,
                    },
                    {
                        "$set": {
                            "status": "invited",
                            "updated_at": datetime.now(timezone.utc),
                        },
                        "$unset": {"password_hash": "", "activated_at": ""},
                    },
                )
            self.mongo.invitations.update_one(
                {"id": invitation["id"], "status": {"$in": ["accepting", "accepted"]}},
                {
                    "$set": {"status": "sent", "updated_at": datetime.now(timezone.utc)},
                    "$unset": {"accepted_at": ""},
                },
            )
            raise
        try:
            self._audit("invitation_accepted", invitation, actor_id=user["id"])
        except Exception as exc:
            self.mongo.invitations.update_one(
                {"id": invitation["id"]},
                {"$set": {"audit_error": str(exc)[:400]}},
            )
        return {
            "accepted": True,
            "workspace_name": company["name"],
            "email": user["email"],
        }
