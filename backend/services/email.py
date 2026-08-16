from dataclasses import dataclass
from typing import Protocol

import httpx

from ..config import APP_ENV, EMAIL_FROM, EMAIL_PROVIDER, RESEND_API_KEY


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str


@dataclass(frozen=True)
class EmailDeliveryResult:
    delivered: bool
    provider: str
    message_id: str | None = None
    error: str | None = None


class TransactionalEmailService(Protocol):
    provider_name: str

    def send(self, message: EmailMessage) -> EmailDeliveryResult: ...


class ResendEmailService:
    provider_name = "resend"

    def __init__(self, api_key: str, email_from: str):
        self.api_key = api_key
        self.email_from = email_from

    def send(self, message: EmailMessage) -> EmailDeliveryResult:
        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self.email_from,
                    "to": [message.to],
                    "subject": message.subject,
                    "html": message.html,
                    "text": message.text,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()
            return EmailDeliveryResult(
                delivered=True,
                provider=self.provider_name,
                message_id=payload.get("id"),
            )
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("message") or exc.response.text
            except Exception:
                detail = exc.response.text
            return EmailDeliveryResult(
                delivered=False,
                provider=self.provider_name,
                error=f"Resend rejected the message: {str(detail)[:400]}",
            )
        except Exception as exc:
            return EmailDeliveryResult(
                delivered=False,
                provider=self.provider_name,
                error=f"Email delivery failed: {str(exc)[:400]}",
            )


class UnavailableEmailService:
    provider_name = "unavailable"

    def __init__(self, reason: str):
        self.reason = reason

    def send(self, message: EmailMessage) -> EmailDeliveryResult:
        return EmailDeliveryResult(
            delivered=False,
            provider=self.provider_name,
            error=self.reason,
        )


class MemoryEmailService:
    """Test-only provider. It is unavailable unless APP_ENV explicitly enables testing."""

    provider_name = "memory"

    def __init__(self):
        self.messages: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> EmailDeliveryResult:
        self.messages.append(message)
        return EmailDeliveryResult(
            delivered=True,
            provider=self.provider_name,
            message_id=f"memory-{len(self.messages)}",
        )


def build_email_service() -> TransactionalEmailService:
    if EMAIL_PROVIDER == "memory":
        if APP_ENV == "testing":
            return MemoryEmailService()
        return UnavailableEmailService(
            "The memory email provider is restricted to APP_ENV=testing."
        )
    if EMAIL_PROVIDER != "resend":
        return UnavailableEmailService(
            f"Unsupported transactional email provider: {EMAIL_PROVIDER}"
        )
    if not RESEND_API_KEY or not EMAIL_FROM:
        return UnavailableEmailService(
            "Transactional email is not configured. Set RESEND_API_KEY and EMAIL_FROM, then resend the invitation."
        )
    return ResendEmailService(RESEND_API_KEY, EMAIL_FROM)
