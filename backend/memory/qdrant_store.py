import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from langgraph.store.base import (
    BaseStore, Item, SearchItem, GetOp, PutOp, SearchOp,
    ListNamespacesOp, Op
)
from qdrant_client import QdrantClient, models as qmodels


class QdrantMemoryStore(BaseStore):
    def __init__(
        self,
        client: QdrantClient,
        collection_name: str,
        embeddings,
        dims: int,
        max_namespace_depth: int = 8,
    ):
        self.client = client
        self.collection_name = collection_name
        self.embeddings = embeddings
        self.dims = dims
        self.max_namespace_depth = max_namespace_depth
        self._ensure_collection()

    def _ensure_collection(self):
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=qmodels.VectorParams(
                    size=self.dims,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            for i in range(self.max_namespace_depth):
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=f"ns_{i}",
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="key",
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )

    @staticmethod
    def _point_id(namespace: tuple, key: str) -> str:
        raw = "/".join(namespace) + "::" + key
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, raw))

    @staticmethod
    def _extract_text(value: dict, index) -> str:
        fields = index if isinstance(index, list) else ["$"]
        if not fields or fields == ["$"]:
            return json.dumps(value, sort_keys=True, default=str)
        parts = []
        for field in fields:
            if field == "$":
                parts.append(json.dumps(value, sort_keys=True, default=str))
                continue
            cur = value
            found = True
            for part in field.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    found = False
                    break
            if found:
                parts.append(str(cur))
        return "\n".join(parts) if parts else json.dumps(value, sort_keys=True, default=str)

    def _item_from_point(self, point) -> Item:
        payload = point.payload
        return Item(
            value=payload["value"],
            key=payload["key"],
            namespace=tuple(payload["namespace"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
        )

    def _namespace_filter(self, namespace_prefix: tuple, extra_filter: Optional[dict] = None):
        must = []
        for i, part in enumerate(namespace_prefix):
            must.append(qmodels.FieldCondition(
                key=f"ns_{i}",
                match=qmodels.MatchValue(value=part),
            ))
        if extra_filter:
            for k, v in extra_filter.items():
                must.append(qmodels.FieldCondition(
                    key=f"value.{k}",
                    match=qmodels.MatchValue(value=v),
                ))
        return qmodels.Filter(must=must) if must else None

    def _get(self, namespace: tuple, key: str):
        points = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[self._point_id(namespace, key)],
            with_payload=True,
        )
        return self._item_from_point(points[0]) if points else None

    def _put(self, namespace: tuple, key: str, value: dict, index):
        now = datetime.now(timezone.utc).isoformat()
        existing = self._get(namespace, key)
        created_at = existing.created_at.isoformat() if existing else now
        if index is False:
            vector = [0.0] * self.dims
        else:
            text = self._extract_text(value, index)
            vector = self.embeddings.embed_documents([text])[0]

        payload = {
            "namespace": list(namespace),
            "key": key,
            "value": value,
            "created_at": created_at,
            "updated_at": now,
            "ns_depth": len(namespace),
        }
        for i, part in enumerate(namespace[:self.max_namespace_depth]):
            payload[f"ns_{i}"] = part

        self.client.upsert(
            collection_name=self.collection_name,
            points=[qmodels.PointStruct(
                id=self._point_id(namespace, key),
                vector=vector,
                payload=payload,
            )],
        )

    def _delete(self, namespace: tuple, key: str):
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=qmodels.PointIdsList(
                points=[self._point_id(namespace, key)]
            ),
        )

    def _search(self, op: SearchOp):
        filt = self._namespace_filter(op.namespace_prefix, op.filter)
        if op.query:
            query_vector = self.embeddings.embed_query(op.query)
            hits = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=filt,
                limit=op.limit,
                offset=op.offset,
                with_payload=True,
            ).points
            return [
                SearchItem(
                    value=(item := self._item_from_point(h)).value,
                    key=item.key,
                    namespace=item.namespace,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    score=h.score,
                )
                for h in hits
            ]

        points, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=filt,
            limit=op.limit + op.offset,
            with_payload=True,
        )
        page = points[op.offset:op.offset + op.limit]
        return [
            SearchItem(
                value=(item := self._item_from_point(p)).value,
                key=item.key,
                namespace=item.namespace,
                created_at=item.created_at,
                updated_at=item.updated_at,
                score=None,
            )
            for p in page
        ]

    def _list_namespaces(self, op: ListNamespacesOp):
        points, _ = self.client.scroll(
            collection_name=self.collection_name,
            limit=10000,
            with_payload=True,
        )
        namespaces = set()
        for p in points:
            ns = tuple(p.payload["namespace"])
            if op.max_depth:
                ns = ns[:op.max_depth]
            namespaces.add(ns)

        if op.match_conditions:
            filtered = set()
            for ns in namespaces:
                ok = True
                for cond in op.match_conditions:
                    path = cond.path
                    segment = ns[:len(path)] if cond.match_type == "prefix" else (
                        ns[-len(path):] if len(path) <= len(ns) else ns
                    )
                    if len(segment) != len(path):
                        ok = False
                        break
                    if any(b != "*" and a != b for a, b in zip(segment, path)):
                        ok = False
                        break
                if ok:
                    filtered.add(ns)
            namespaces = filtered

        result = sorted(namespaces)
        return result[op.offset:op.offset + op.limit]

    def batch(self, ops: Iterable[Op]) -> list:
        results = []
        put_ops = {}
        for op in ops:
            if isinstance(op, GetOp):
                results.append(self._get(op.namespace, op.key))
            elif isinstance(op, SearchOp):
                results.append(self._search(op))
            elif isinstance(op, ListNamespacesOp):
                results.append(self._list_namespaces(op))
            elif isinstance(op, PutOp):
                put_ops[(op.namespace, op.key)] = op
                results.append(None)
            else:
                raise ValueError(f"Unsupported operation: {op}")

        for (namespace, key), op in put_ops.items():
            if op.value is None:
                self._delete(namespace, key)
            else:
                self._put(namespace, key, op.value, getattr(op, "index", None))
        return results

    async def abatch(self, ops: Iterable[Op]) -> list:
        return await asyncio.to_thread(self.batch, list(ops))
