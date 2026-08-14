"""Assign legacy policy vectors to one tenant.

Usage: python migrate_legacy_policy.py <tenant_id>
Only run this for a collection that previously belonged to one company.

LangChain Qdrant stores Document.metadata under the `metadata` payload key,
so this script writes tenant_id into metadata for old points.
"""
import sys
from qdrant_client import QdrantClient
from backend.config import QDRANT_MEMORY_URL, QDRANT_API_KEY, POLICY_COLLECTION

if len(sys.argv) != 2:
    raise SystemExit("Usage: python migrate_legacy_policy.py <tenant_id>")

tenant_id = sys.argv[1]
client = QdrantClient(url=QDRANT_MEMORY_URL, api_key=QDRANT_API_KEY)
if not client.collection_exists(POLICY_COLLECTION):
    raise SystemExit(f"Collection {POLICY_COLLECTION!r} does not exist")

updated = 0
offset = None
while True:
    points, next_offset = client.scroll(
        collection_name=POLICY_COLLECTION,
        offset=offset,
        limit=100,
        with_payload=True,
        with_vectors=False,
    )
    if not points:
        break

    for point in points:
        payload = point.payload or {}
        metadata = dict(payload.get("metadata") or {})
        if metadata.get("tenant_id"):
            continue

        # Older versions may have stored tenant_id at the payload root.
        # Preserve any existing metadata while moving that value into it.
        legacy_tenant = payload.get("tenant_id") or tenant_id
        metadata["tenant_id"] = legacy_tenant
        client.set_payload(
            collection_name=POLICY_COLLECTION,
            payload={"metadata": metadata},
            points=[point.id],
        )
        updated += 1

    if next_offset is None:
        break
    offset = next_offset

print(f"Assigned tenant_id={tenant_id} to {updated} legacy policy points.")
