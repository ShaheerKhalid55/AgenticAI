from datetime import datetime, timezone
from io import BytesIO
import asyncio
import re
import uuid

from fastapi import APIRouter, BackgroundTasks, File, UploadFile, HTTPException, Depends, status
from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..auth.security import require_role

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Smaller batches make indexing progress visible and keep partial failures easy to clean up.
INDEX_BATCH_SIZE = 32


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def _public_document(doc: dict) -> dict:
    total_chunks = int(doc.get("total_chunks", doc.get("chunks", 0)) or 0)
    indexed_chunks = int(doc.get("indexed_chunks", 0) or 0)
    progress = 0
    if total_chunks:
        progress = min(100, round(indexed_chunks * 100 / total_chunks))
    elif doc.get("status") == "active":
        progress = 100

    return {
        "id": doc.get("id"),
        "tenant_id": doc.get("tenant_id"),
        "name": doc.get("name"),
        "version": doc.get("version", 1),
        "status": doc.get("status", "active"),
        "uploaded_at": doc.get("uploaded_at"),
        "uploaded_by": doc.get("uploaded_by"),
        "size_bytes": doc.get("size_bytes", 0),
        "pages": doc.get("pages", 0),
        "chunks": doc.get("chunks", 0),
        "total_chunks": total_chunks,
        "indexed_chunks": indexed_chunks,
        "progress": progress,
        "error": doc.get("error"),
    }


def _set_status(services, tenant_id: str, document_id: str, status_value: str, **fields):
    update = {"status": status_value, **fields}
    services.mongo.documents.update_one(
        {"id": document_id, "tenant_id": tenant_id},
        {"$set": update},
    )


def _index_document_in_background(services, tenant_id: str, document_id: str, chunks: list[Document]):
    """Write every chunk, but never publish until all vectors are verified."""
    document = services.mongo.documents.find_one({"id": document_id, "tenant_id": tenant_id})
    if not document:
        return

    version = int(document.get("version", 1))
    total_chunks = len(chunks)

    try:
        _set_status(services, tenant_id, document_id, "indexing",
                    total_chunks=total_chunks, indexed_chunks=0, chunks=0, error=None)

        indexed = 0
        for start_idx in range(0, total_chunks, INDEX_BATCH_SIZE):
            current = services.mongo.documents.find_one(
                {"id": document_id, "tenant_id": tenant_id},
                {"status": 1},
            )
            if not current:
                return
            current_status = current.get("status", "indexing")
            if current_status in {"failed", "deleted"}:
                return
            if current_status not in {"indexing", "archived"}:
                return

            batch_status = "archived" if current_status == "archived" else "indexing"
            batch = chunks[start_idx:start_idx + INDEX_BATCH_SIZE]
            services.qdrant.index_documents(
                batch, tenant_id, document_id, version, batch_status
            )
            indexed += len(batch)

            after = services.mongo.documents.find_one(
                {"id": document_id, "tenant_id": tenant_id},
                {"status": 1},
            )
            if not after:
                return
            persisted_status = after.get("status", batch_status)
            if persisted_status not in {"indexing", "archived"}:
                return
            services.mongo.documents.update_one(
                {"id": document_id, "tenant_id": tenant_id},
                {"$set": {"indexed_chunks": indexed, "chunks": indexed}},
            )

        actual_points = services.qdrant.count_policy_document(tenant_id, document_id)
        if actual_points != total_chunks:
            _set_status(
                services, tenant_id, document_id, "failed",
                chunks=actual_points, indexed_chunks=actual_points,
                total_chunks=total_chunks,
                error=f"Index verification failed: expected {total_chunks} vectors but found {actual_points}.",
            )
            return

        final_doc = services.mongo.documents.find_one(
            {"id": document_id, "tenant_id": tenant_id},
            {"status": 1, "name": 1, "pages": 1},
        )
        if not final_doc:
            return

        final_status = final_doc.get("status", "indexing")
        if final_status == "archived":
            services.qdrant.set_policy_status(tenant_id, document_id, "archived")
            _set_status(services, tenant_id, document_id, "archived",
                        pages=final_doc.get("pages", 0), chunks=total_chunks,
                        total_chunks=total_chunks, indexed_chunks=total_chunks, error=None)
            return

        if final_status != "indexing":
            return

        # Verify one more time immediately before publication.
        actual_points = services.qdrant.count_policy_document(tenant_id, document_id)
        if actual_points != total_chunks:
            raise RuntimeError(
                f"Final publication check failed: expected {total_chunks} vectors but found {actual_points}."
            )

        filename = final_doc.get("name", "policy.pdf")

        # Publish vectors first, then atomically claim the MongoDB state. If an
        # archive request wins the race, the conditional update below will fail
        # and we immediately roll the Qdrant vectors back to archived.
        services.qdrant.set_policy_status(tenant_id, document_id, "active")

        claimed = services.mongo.documents.update_one(
            {"id": document_id, "tenant_id": tenant_id, "status": "indexing"},
            {"$set": {
                "status": "active",
                "pages": final_doc.get("pages", 0),
                "chunks": total_chunks,
                "total_chunks": total_chunks,
                "indexed_chunks": total_chunks,
                "error": None,
            }},
        )
        if claimed.modified_count != 1:
            latest = services.mongo.documents.find_one(
                {"id": document_id, "tenant_id": tenant_id}, {"status": 1}
            )
            if latest and latest.get("status") == "archived":
                services.qdrant.set_policy_status(tenant_id, document_id, "archived")
            return

        # Only after the new version has been successfully claimed ACTIVE do we
        # retire the previous active version.
        previous = list(services.mongo.documents.find({
            "tenant_id": tenant_id, "name": filename, "status": "active",
            "id": {"$ne": document_id},
        }))
        for old in previous:
            services.mongo.documents.update_one(
                {"id": old["id"], "tenant_id": tenant_id},
                {"$set": {"status": "archived"}},
            )
            services.qdrant.set_policy_status(tenant_id, old["id"], "archived")
    except Exception as exc:
        try:
            services.qdrant.delete_policy_document(tenant_id, document_id)
        except Exception:
            pass
        current = services.mongo.documents.find_one(
            {"id": document_id, "tenant_id": tenant_id}, {"status": 1}
        )
        if current and current.get("status") == "archived":
            _set_status(services, tenant_id, document_id, "archived",
                        chunks=0, indexed_chunks=0, error=None)
        else:
            _set_status(services, tenant_id, document_id, "failed",
                        chunks=0, indexed_chunks=0, error=str(exc)[:500])


@router.get("")
def list_documents(current_user: dict = Depends(require_role("company_admin"))):
    from ..main import services
    docs = services.mongo.documents.find(
        {"tenant_id": current_user["tenant_id"]},
        {"_id": 0},
    ).sort([("name", 1), ("version", -1)])
    return [_public_document(doc) for doc in docs]


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    current_user: dict = Depends(require_role("company_admin")),
):
    from ..main import services

    if not files:
        raise HTTPException(400, "Please upload at least one PDF")

    tenant_id = current_user["tenant_id"]
    uploaded_by = current_user["sub"]
    splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=100)
    results = []

    for file in files:
        filename = _clean_name(file.filename or "")
        if not filename.lower().endswith(".pdf"):
            results.append({
                "id": None, "name": filename or "File", "version": None,
                "status": "failed", "pages": 0, "chunks": 0,
                "total_chunks": 0, "indexed_chunks": 0, "progress": 0,
                "error": "File is not a PDF",
            })
            continue

        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            results.append({
                "id": None, "name": filename, "version": None,
                "status": "failed", "pages": 0, "chunks": 0,
                "total_chunks": 0, "indexed_chunks": 0, "progress": 0,
                "error": "File exceeds the 20 MB limit",
            })
            continue

        try:
            reader = PdfReader(BytesIO(data))
        except Exception as exc:
            results.append({
                "id": None, "name": filename, "version": None,
                "status": "failed", "pages": 0, "chunks": 0,
                "total_chunks": 0, "indexed_chunks": 0, "progress": 0,
                "error": f"Could not parse PDF: {exc}",
            })
            continue

        latest = services.mongo.documents.find_one(
            {"tenant_id": tenant_id, "name": filename},
            sort=[("version", -1)],
        )
        version = int(latest.get("version", 0)) + 1 if latest else 1
        document_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        try:
            pages = []
            for page_idx, page in enumerate(reader.pages):
                text = page.extract_text()
                if text and text.strip():
                    pages.append(Document(
                        page_content=text,
                        metadata={
                            "source": filename,
                            "page": page_idx,
                            "tenant_id": tenant_id,
                            "document_id": document_id,
                            "document_version": version,
                            "policy_status": "indexing",
                        },
                    ))

            if not pages:
                raise ValueError("No readable text was found in the PDF")

            chunks = splitter.split_documents(pages)
            if not chunks:
                raise ValueError("No searchable text chunks were created from the PDF")

            document_record = {
                "id": document_id,
                "tenant_id": tenant_id,
                "name": filename,
                "version": version,
                "status": "indexing",
                "uploaded_at": now,
                "uploaded_by": uploaded_by,
                "size_bytes": len(data),
                "pages": len(pages),
                "chunks": 0,
                "total_chunks": len(chunks),
                "indexed_chunks": 0,
                "error": None,
            }
            services.mongo.documents.insert_one(document_record)

            # Fast HTTP response. Actual embedding/vector work happens after the
            # response and updates Mongo progress after every batch.
            background_tasks.add_task(
                _index_document_in_background,
                services,
                tenant_id,
                document_id,
                chunks,
            )

            results.append({
                "id": document_id,
                "name": filename,
                "version": version,
                "status": "indexing",
                "pages": len(pages),
                "chunks": 0,
                "total_chunks": len(chunks),
                "indexed_chunks": 0,
                "progress": 0,
            })
        except HTTPException:
            raise
        except Exception as exc:
            results.append({
                "id": document_id,
                "name": filename,
                "version": version,
                "status": "failed",
                "pages": 0,
                "chunks": 0,
                "total_chunks": 0,
                "indexed_chunks": 0,
                "progress": 0,
                "error": str(exc)[:500],
            })

    accepted = [r for r in results if r["status"] == "indexing"]
    failed = [r for r in results if r["status"] == "failed"]

    return {
        "success": True,
        "documents": len(accepted),
        "chunks": 0,
        "results": results,
        "message": (
            "Upload accepted. Policy documents are now being indexed."
            if accepted else "No documents were accepted for indexing."
        ),
        "failed": len(failed),
    }


@router.patch("/{document_id}/archive")
def archive_document(document_id: str, current_user: dict = Depends(require_role("company_admin"))):
    from ..main import services
    tenant_id = current_user["tenant_id"]
    doc = services.mongo.documents.find_one({"id": document_id, "tenant_id": tenant_id})
    if not doc:
        raise HTTPException(404, "Policy document not found")

    current_status = doc.get("status", "active")
    if current_status == "archived":
        return _public_document(doc)
    if current_status not in {"active", "indexing", "processing"}:
        raise HTTPException(400, f"Cannot archive a document with status '{current_status}'")

    # Immediately remove this document from the active lifecycle and from the
    # searchable vector set. The indexer, if still running, will continue writing
    # remaining chunks with archived status.
    services.mongo.documents.update_one(
        {"id": document_id, "tenant_id": tenant_id},
        {"$set": {"status": "archived"}},
    )
    services.qdrant.set_policy_status(tenant_id, document_id, "archived")
    doc["status"] = "archived"
    return _public_document(doc)


@router.patch("/{document_id}/restore")
def restore_document(document_id: str, current_user: dict = Depends(require_role("company_admin"))):
    from ..main import services
    tenant_id = current_user["tenant_id"]
    doc = services.mongo.documents.find_one({"id": document_id, "tenant_id": tenant_id})
    if not doc:
        raise HTTPException(404, "Policy document not found")
    if doc.get("status") == "active":
        return _public_document(doc)
    if doc.get("status") != "archived":
        raise HTTPException(400, "Only archived documents can be restored")

    expected = int(doc.get("total_chunks", doc.get("chunks", 0)) or 0)
    stored = services.qdrant.count_policy_document(tenant_id, document_id)
    if expected <= 0 or stored != expected:
        indexed = int(doc.get("indexed_chunks", stored) or 0)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Document is not fully indexed yet ({indexed} / {expected} chunks; {stored} vectors in Qdrant). Wait for indexing to finish before restoring it.",
        )

    current = list(services.mongo.documents.find({
        "tenant_id": tenant_id, "name": doc["name"], "status": "active",
        "id": {"$ne": document_id},
    }))
    for old in current:
        services.mongo.documents.update_one(
            {"id": old["id"], "tenant_id": tenant_id},
            {"$set": {"status": "archived"}},
        )
        services.qdrant.set_policy_status(tenant_id, old["id"], "archived")

    services.qdrant.set_policy_status(tenant_id, document_id, "active")
    services.mongo.documents.update_one(
        {"id": document_id, "tenant_id": tenant_id},
        {"$set": {
            "status": "active", "error": None, "chunks": expected,
            "total_chunks": expected, "indexed_chunks": expected,
        }},
    )
    doc.update({"status": "active", "chunks": expected, "total_chunks": expected, "indexed_chunks": expected})
    return _public_document(doc)


@router.delete("/{document_id}")
def delete_document(document_id: str, current_user: dict = Depends(require_role("company_admin"))):
    from ..main import services
    tenant_id = current_user["tenant_id"]
    doc = services.mongo.documents.find_one({"id": document_id, "tenant_id": tenant_id})
    if not doc:
        raise HTTPException(404, "Policy document not found")

    services.qdrant.delete_policy_document(tenant_id, document_id)
    services.mongo.documents.delete_one({"id": document_id, "tenant_id": tenant_id})
    return {"success": True, "id": document_id}


@router.get("/status")
def knowledge_base_status(current_user: dict = Depends(require_role("company_admin", "employee"))):
    from ..main import services
    tenant_id = current_user["tenant_id"]
    indexing = list(services.mongo.documents.find(
        {"tenant_id": tenant_id, "status": "indexing"},
        {"_id": 0},
    ).sort("uploaded_at", -1))
    active = services.mongo.documents.count_documents({"tenant_id": tenant_id, "status": "active"})
    return {
        "ready": active > 0,
        "indexing": [_public_document(doc) for doc in indexing],
    }
