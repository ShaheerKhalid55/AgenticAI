import re
from datetime import datetime, timezone
from typing import Optional

import pymongo

from ..config import MONGODB_URI, MONGODB_DB_NAME, SESSIONS_COLLECTION


FALLBACK_SESSION_TITLE_PATTERN = r"^Chat · [A-Z][a-z]{2} [0-9]{1,2}, [0-9]{1,2}:[0-9]{2} [AP]M$"


DEFAULT_ASSISTANT = {
    "name": "Knowledge Assistant",
    "description": "An AI assistant grounded in your workspace knowledge base.",
    "system_instructions": (
        "Answer questions using the workspace knowledge base when it is relevant. "
        "Be clear about uncertainty and do not invent facts that are not supported by available sources."
    ),
    "welcome_message": "Hello! What would you like to know?",
    "placeholder": "Ask Nexa anything...",
    "icon": None,
    "knowledge_base_id": "default",
    "enabled_tools": ["knowledge_base", "memory", "web_fetch"],
    "memory_settings": {
        "conversation_memory": True,
        "long_term_memory": True,
        "save_personal_preferences": True,
    },
    "citation_requirements": {
        "enabled": True,
        "required": True,
        "include_document_name": True,
        "include_page": True,
        "include_chunk": True,
    },
    "starter_questions": [],
    "status": "active",
}


class MongoService:
    def __init__(self):
        self.client = pymongo.MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        self.db = self.client[MONGODB_DB_NAME]
        self.sessions = self.db[SESSIONS_COLLECTION]
        self.users = self.db["users"]
        self.companies = self.db["companies"]
        self.documents = self.db["policy_documents"]
        self.assistants = self.db["assistant_configurations"]
        self.invitations = self.db["user_invitations"]
        self.invitation_audit = self.db["invitation_audit"]

        self.users.create_index("email", unique=True)
        self.users.create_index([("tenant_id", 1), ("email", 1)])
        self.companies.create_index("id", unique=True)
        self.documents.create_index([("tenant_id", 1), ("name", 1), ("version", -1)])
        self.documents.create_index([("tenant_id", 1), ("status", 1), ("uploaded_at", -1)])
        self.sessions.create_index([("tenant_id", 1), ("user_id", 1), ("updated_at", -1)])
        self.sessions.create_index(
            [("tenant_id", 1), ("user_id", 1), ("thread_id", 1)],
            unique=True,
        )
        self.assistants.create_index([("tenant_id", 1), ("id", 1)], unique=True)
        self.assistants.create_index([("tenant_id", 1), ("status", 1)])
        self.invitations.create_index("id", unique=True)
        self.invitations.create_index("token_hash", unique=True)
        self.invitations.create_index(
            [("tenant_id", 1), ("user_id", 1), ("created_at", -1)]
        )
        self.invitations.create_index([("status", 1), ("expires_at", 1)])
        self.invitation_audit.create_index(
            [("tenant_id", 1), ("user_id", 1), ("created_at", -1)]
        )

    def get_assistant(self, tenant_id: str, assistant_id: str = "default") -> dict:
        assistant = self.assistants.find_one(
            {"tenant_id": tenant_id, "id": assistant_id}, {"_id": 0}
        )
        if assistant:
            return assistant
        now = datetime.now(timezone.utc)
        assistant = {
            **DEFAULT_ASSISTANT,
            "id": assistant_id,
            "tenant_id": tenant_id,
            "created_at": now,
            "updated_at": now,
        }
        self.assistants.update_one(
            {"tenant_id": tenant_id, "id": assistant_id},
            {"$setOnInsert": assistant},
            upsert=True,
        )
        return assistant

    def update_assistant(self, tenant_id: str, assistant_id: str, updates: dict) -> dict:
        self.get_assistant(tenant_id, assistant_id)
        updates = {**updates, "updated_at": datetime.now(timezone.utc)}
        self.assistants.update_one(
            {"tenant_id": tenant_id, "id": assistant_id}, {"$set": updates}
        )
        return self.assistants.find_one(
            {"tenant_id": tenant_id, "id": assistant_id}, {"_id": 0}
        )

    def ping(self) -> bool:
        try:
            self.client.admin.command("ping")
            return True
        except Exception:
            return False

    def create_session(self, tenant_id: str, user_id: str, thread_id: str, title: Optional[str] = None):
        now = datetime.now(timezone.utc)
        supplied_title = (title or "").strip()
        title = supplied_title or now.strftime("Chat · %b %d, %I:%M %p").replace(" 0", " ")
        self.sessions.update_one(
            {"tenant_id": tenant_id, "user_id": user_id, "thread_id": thread_id},
            {"$setOnInsert": {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "thread_id": thread_id,
                "title": title,
                "title_source": "manual" if supplied_title else "fallback",
                "created_at": now,
                "updated_at": now,
            }},
            upsert=True,
        )

    def session_belongs_to(self, tenant_id: str, user_id: str, thread_id: str) -> bool:
        return self.sessions.find_one({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "thread_id": thread_id,
        }) is not None

    def list_sessions(self, tenant_id: str, user_id: str, query: Optional[str] = None):
        filters = {"tenant_id": tenant_id, "user_id": user_id}
        query = (query or "").strip()
        if query:
            filters["title"] = {"$regex": re.escape(query), "$options": "i"}
        return list(self.sessions.find(
            filters,
            {"_id": 0},
        ).sort("updated_at", -1))

    def touch_session(self, tenant_id: str, user_id: str, thread_id: str):
        self.sessions.update_one(
            {"tenant_id": tenant_id, "user_id": user_id, "thread_id": thread_id},
            {"$set": {"updated_at": datetime.now(timezone.utc)}},
        )

    def set_automatic_session_title(self, tenant_id: str, user_id: str, thread_id: str, title: str):
        """Set a first-message title without overwriting automatic or manual titles."""
        title = " ".join(title.split()).strip()
        if not title:
            return False
        if len(title) > 50:
            title = f"{title[:50].rstrip()}…"
        result = self.sessions.update_one(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "thread_id": thread_id,
                "$or": [
                    {"title_source": "fallback"},
                    {
                        "title_source": {"$exists": False},
                        "title": {"$regex": FALLBACK_SESSION_TITLE_PATTERN},
                    },
                    {"title": {"$exists": False}},
                    {"title": None},
                    {"title": ""},
                ],
            },
            {"$set": {
                "title": title,
                "title_source": "automatic",
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        return result.modified_count > 0

    def rename_session(self, tenant_id: str, user_id: str, thread_id: str, title: str):
        title = title.strip()
        if title:
            self.sessions.update_one(
                {"tenant_id": tenant_id, "user_id": user_id, "thread_id": thread_id},
                {"$set": {
                    "title": title[:80],
                    "title_source": "manual",
                    "updated_at": datetime.now(timezone.utc),
                }},
            )

    def delete_session(self, tenant_id: str, user_id: str, thread_id: str):
        self.sessions.delete_one({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "thread_id": thread_id,
        })
