"""Assign legacy policy vectors to one tenant.

Usage: python migrate_legacy_policy.py <tenant_id>
Only run this for a collection that previously belonged to one company.
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
    ids = [p.id for p in points if not (p.payload or {}).get("tenant_id")]
    if ids:
        client.set_payload(
            collection_name=POLICY_COLLECTION,
            payload={"tenant_id": tenant_id},
            points=ids,
        )
        updated += len(ids)
    if next_offset is None:
        break
    offset = next_offset

print(f"Assigned tenant_id={tenant_id} to {updated} legacy policy points.")
