from datetime import datetime, timezone
from typing import Optional
import pymongo

from ..config import MONGODB_URI, MONGODB_DB_NAME, SESSIONS_COLLECTION


class MongoService:
    def __init__(self):
        self.client = pymongo.MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        self.db = self.client[MONGODB_DB_NAME]
        self.sessions = self.db[SESSIONS_COLLECTION]
        self.users = self.db["users"]
        self.companies = self.db["companies"]

        self.users.create_index("email", unique=True)
        self.users.create_index([("tenant_id", 1), ("email", 1)])
        self.companies.create_index("id", unique=True)
        self.sessions.create_index([("tenant_id", 1), ("user_id", 1), ("updated_at", -1)])
        self.sessions.create_index(
            [("tenant_id", 1), ("user_id", 1), ("thread_id", 1)],
            unique=True,
        )

    def ping(self) -> bool:
        try:
            self.client.admin.command("ping")
            return True
        except Exception:
            return False

    def create_session(self, tenant_id: str, user_id: str, thread_id: str, title: Optional[str] = None):
        now = datetime.now(timezone.utc)
        title = title or now.strftime("Chat · %b %d, %I:%M %p").replace(" 0", " ")
        self.sessions.update_one(
            {"tenant_id": tenant_id, "user_id": user_id, "thread_id": thread_id},
            {"$setOnInsert": {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "thread_id": thread_id,
                "title": title,
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

    def list_sessions(self, tenant_id: str, user_id: str):
        return list(self.sessions.find(
            {"tenant_id": tenant_id, "user_id": user_id},
            {"_id": 0},
        ).sort("updated_at", -1))

    def touch_session(self, tenant_id: str, user_id: str, thread_id: str, title: Optional[str] = None):
        update = {"updated_at": datetime.now(timezone.utc)}
        if title:
            update["title"] = title[:80]
        self.sessions.update_one(
            {"tenant_id": tenant_id, "user_id": user_id, "thread_id": thread_id},
            {"$set": update},
        )

    def rename_session(self, tenant_id: str, user_id: str, thread_id: str, title: str):
        title = title.strip()
        if title:
            self.sessions.update_one(
                {"tenant_id": tenant_id, "user_id": user_id, "thread_id": thread_id},
                {"$set": {"title": title[:80]}},
            )

    def delete_session(self, tenant_id: str, user_id: str, thread_id: str):
        self.sessions.delete_one({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "thread_id": thread_id,
        })
