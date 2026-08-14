from datetime import datetime, timezone
from io import BytesIO
import re
import uuid

from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..auth.security import require_role

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def _public_document(doc: dict) -> dict:
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
        "error": doc.get("error"),
    }


@router.get("")
def list_documents(current_user: dict = Depends(require_role("company_admin"))):
    from ..main import services
    docs = services.mongo.documents.find(
        {"tenant_id": current_user["tenant_id"]},
        {"_id": 0},
    ).sort([("name", 1), ("version", -1)])
    return [_public_document(doc) for doc in docs]


@router.post("/upload")
async def upload_documents(
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
            raise HTTPException(400, f"{filename or 'File'} is not a PDF")

        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(413, f"{filename} exceeds the 20 MB limit")

        try:
            reader = PdfReader(BytesIO(data))
        except Exception as exc:
            raise HTTPException(400, f"Could not parse {filename}: {exc}")

        # Version is scoped to the tenant + filename.
        latest = services.mongo.documents.find_one(
            {"tenant_id": tenant_id, "name": filename},
            sort=[("version", -1)],
        )
        version = int(latest.get("version", 0)) + 1 if latest else 1
        document_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        document_record = {
            "id": document_id,
            "tenant_id": tenant_id,
            "name": filename,
            "version": version,
            "status": "processing",
            "uploaded_at": now,
            "uploaded_by": uploaded_by,
            "size_bytes": len(data),
            "pages": 0,
            "chunks": 0,
            "error": None,
        }
        services.mongo.documents.insert_one(document_record)

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
                            "policy_status": "processing",
                        },
                    ))

            if not pages:
                raise ValueError("No readable text was found in the PDF")

            chunks = splitter.split_documents(pages)
            await __import__("asyncio").to_thread(
                services.qdrant.index_documents,
                chunks,
                tenant_id,
                document_id,
                version,
                "processing",
            )

            # Only after the new version has indexed successfully do we archive
            # the previous active version. This keeps the old policy available
            # if indexing fails.
            previous = list(services.mongo.documents.find({
                "tenant_id": tenant_id,
                "name": filename,
                "status": "active",
                "id": {"$ne": document_id},
            }))
            for old in previous:
                services.mongo.documents.update_one(
                    {"id": old["id"], "tenant_id": tenant_id},
                    {"$set": {"status": "archived"}},
                )
                await __import__("asyncio").to_thread(
                    services.qdrant.set_policy_status,
                    tenant_id,
                    old["id"],
                    "archived",
                )

            await __import__("asyncio").to_thread(
                services.qdrant.set_policy_status,
                tenant_id,
                document_id,
                "active",
            )
            services.mongo.documents.update_one(
                {"id": document_id, "tenant_id": tenant_id},
                {"$set": {
                    "status": "active",
                    "pages": len(pages),
                    "chunks": len(chunks),
                    "error": None,
                }},
            )
            results.append({
                "name": filename,
                "version": version,
                "status": "active",
                "pages": len(pages),
                "chunks": len(chunks),
            })
        except Exception as exc:
            services.mongo.documents.update_one(
                {"id": document_id, "tenant_id": tenant_id},
                {"$set": {"status": "failed", "error": str(exc)[:500]}},
            )
            # Remove any partially indexed vectors for this upload.
            try:
                await __import__("asyncio").to_thread(
                    services.qdrant.delete_policy_document,
                    tenant_id,
                    document_id,
                )
            except Exception:
                pass
            results.append({
                "name": filename,
                "version": version,
                "status": "failed",
                "pages": 0,
                "chunks": 0,
                "error": str(exc)[:500],
            })

    successful = [r for r in results if r["status"] == "active"]
    failed = [r for r in results if r["status"] == "failed"]
    if not successful and failed:
        raise HTTPException(500, f"Policy processing failed: {failed[0].get('error', 'Unknown error')}")

    return {
        "success": True,
        "documents": len(successful),
        "chunks": sum(r["chunks"] for r in successful),
        "results": results,
        "message": "Policy library updated successfully for this company.",
    }


@router.patch("/{document_id}/archive")
def archive_document(document_id: str, current_user: dict = Depends(require_role("company_admin"))):
    from ..main import services
    tenant_id = current_user["tenant_id"]
    doc = services.mongo.documents.find_one({"id": document_id, "tenant_id": tenant_id})
    if not doc:
        raise HTTPException(404, "Policy document not found")
    if doc.get("status") == "archived":
        return _public_document(doc)
    if doc.get("status") != "active":
        raise HTTPException(400, f"Cannot archive a document with status '{doc.get('status')}'")

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
        raise HTTPException(400, "Only archived policies can be restored")

    # Keep exactly one active version for a policy filename.
    current = services.mongo.documents.find({
        "tenant_id": tenant_id,
        "name": doc["name"],
        "status": "active",
        "id": {"$ne": document_id},
    })
    for old in current:
        services.mongo.documents.update_one(
            {"id": old["id"], "tenant_id": tenant_id},
            {"$set": {"status": "archived"}},
        )
        services.qdrant.set_policy_status(tenant_id, old["id"], "archived")

    services.mongo.documents.update_one(
        {"id": document_id, "tenant_id": tenant_id},
        {"$set": {"status": "active", "error": None}},
    )
    services.qdrant.set_policy_status(tenant_id, document_id, "active")
    doc["status"] = "active"
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
    retriever = services.qdrant.policy_retriever(current_user["tenant_id"])
    return {"ready": retriever is not None}
