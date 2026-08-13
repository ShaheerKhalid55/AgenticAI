from io import BytesIO
from fastapi import APIRouter, File, UploadFile, HTTPException

from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload")
async def upload_documents(files: list[UploadFile] = File(...)):
    from ..main import services

    if not files:
        raise HTTPException(400, "Please upload at least one PDF")

    documents = []
    document_count = 0
    page_count = 0

    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(400, f"{file.filename} is not a PDF")

        data = await file.read()
        try:
            reader = PdfReader(BytesIO(data))
        except Exception as exc:
            raise HTTPException(400, f"Could not parse {file.filename}: {exc}")

        document_count += 1
        for page_idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                documents.append(Document(
                    page_content=text,
                    metadata={
                        "source": file.filename,
                        "page": page_idx,
                    },
                ))
                page_count += 1

    if not documents:
        raise HTTPException(400, "No readable text was found in the uploaded PDFs")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=100,
    )
    chunks = splitter.split_documents(documents)

    await __import__("asyncio").to_thread(
        services.qdrant.index_documents,
        chunks,
    )

    return {
        "success": True,
        "documents": document_count,
        "pages": page_count,
        "chunks": len(chunks),
        "message": "Knowledge base updated successfully.",
    }


@router.get("/status")
def knowledge_base_status():
    from ..main import services
    retriever = services.qdrant.policy_retriever()
    return {"ready": retriever is not None}
