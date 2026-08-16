import sys
from typing import Annotated, Sequence, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_ollama import ChatOllama
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langmem import create_manage_memory_tool, create_search_memory_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from typing_extensions import TypedDict

from ..config import OLLAMA_API_KEY, OLLAMA_CLOUD_HOST, OLLAMA_LLM_MODEL


def extract_text(content: Any) -> str:
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


BASE_PLATFORM_PROMPT = (
    "You are a general-purpose AI knowledge assistant for the current organization. "
    "You can answer questions about any topic; you are not restricted to HR.\n\n"
    "MANDATORY KNOWLEDGE-BASE-FIRST WORKFLOW:\n"
    "1. A tenant knowledge-base search is performed BEFORE you receive the question for answering. "
    "You MUST inspect the injected 'KNOWLEDGE BASE SEARCH RESULT' before drafting or giving an answer. "
    "Do not answer from model knowledge before reviewing that result.\n"
    "2. Examine the returned passages carefully and decide whether they actually contain enough information to answer the question.\n"
    "3. If the retrieved company-document content contains the answer, answer from that content first. "
    "For company-specific facts, uploaded documents are authoritative.\n"
    "4. If the retrieved content does NOT contain enough information, you MAY use general model knowledge, "
    "but MUST begin with: 'Based on my general LLM knowledge (not found in the uploaded company documents):'\n"
    "5. If the question requires company-specific information and the knowledge-base search does not contain it, "
    "say that it was not found in the uploaded company documents rather than inventing it.\n\n"
    "DOCUMENT CITATIONS:\n"
    "- When using an uploaded document, cite the exact source document and page returned by the search result.\n"
    "- Never invent a document name, page, or citation.\n"
    "- If several documents are relevant, cite each one.\n\n"
    "HALLUCINATION CONTROL:\n"
    "- Never fabricate document content or citations.\n"
    "- Never claim a document says something unless the retrieved passage supports it.\n"
    "- If neither documents nor general knowledge are sufficient, say you do not know."
)


def build_system_prompt(assistant: dict) -> SystemMessage:
    sections = [BASE_PLATFORM_PROMPT]
    custom = (assistant.get("system_instructions") or "").strip()
    if custom:
        sections.append("ASSISTANT-SPECIFIC INSTRUCTIONS:\n" + custom)

    citations = assistant.get("citation_requirements") or {}
    if citations.get("enabled", True):
        pieces = []
        if citations.get("include_document_name", True):
            pieces.append("document name")
        if citations.get("include_page", True):
            pieces.append("page")
        if citations.get("include_chunk", True):
            pieces.append("chunk")
        if pieces:
            requirement = "must" if citations.get("required", True) else "should"
            sections.append(
                f"Citation settings: answers grounded in workspace documents {requirement} cite "
                + ", ".join(pieces) + ". Never fabricate citations."
            )

    memory = assistant.get("memory_settings") or {}
    if memory.get("long_term_memory", True) and memory.get("save_personal_preferences", True):
        sections.append(
            "Use memory tools only for relevant durable, non-sensitive user information. "
            "Do not store source-document content as personal memory."
        )
    elif memory.get("long_term_memory", True):
        sections.append("You may search long-term memory when useful, but do not save new memories.")

    if "web_fetch" in set(assistant.get("enabled_tools") or []):
        sections.append("Use the fetch tool for user-provided URLs when appropriate and clearly identify fetched web information.")

    return SystemMessage(content="\n\n".join(sections))


class AgentService:
    def __init__(self, qdrant_service, mongo_service):
        self.qdrant = qdrant_service
        self.mongo = mongo_service
        self.memory_store = None
        self.checkpointer = None
        self.graph = None
        self.mcp_tools = []
        self.tools = []

    def tool_catalog(self, assistant: dict) -> list[dict]:
        enabled = set(assistant.get("enabled_tools") or [])
        available = {
            "knowledge_base": self.qdrant is not None,
            "memory": self.memory_store is not None,
            "web_fetch": any(getattr(tool, "name", "") == "fetch" for tool in self.mcp_tools),
        }
        definitions = (
            ("knowledge_base", "Knowledge base", "Search indexed workspace documents."),
            ("memory", "Long-term memory", "Save and recall durable user context."),
            ("web_fetch", "Web fetch (MCP)", "Fetch readable content from user-provided URLs."),
        )
        return [
            {
                "id": tool_id,
                "name": name,
                "description": description,
                "available": available[tool_id],
                "enabled": tool_id in enabled,
                "status": "unavailable" if not available[tool_id] else ("available" if tool_id in enabled else "disabled"),
            }
            for tool_id, name, description in definitions
        ]

    async def initialize(self):
        from ..memory.qdrant_store import QdrantMemoryStore
        from ..config import QDRANT_MEMORY_COLLECTION, MEMORY_EMBEDDING_DIMS, MAX_NAMESPACE_DEPTH

        self.memory_store = QdrantMemoryStore(
            client=self.qdrant.client,
            collection_name=QDRANT_MEMORY_COLLECTION,
            embeddings=self.qdrant.embeddings,
            dims=MEMORY_EMBEDDING_DIMS,
            max_namespace_depth=MAX_NAMESPACE_DEPTH,
        )

        try:
            from langgraph.checkpoint.mongodb import MongoDBSaver
            self.checkpointer = MongoDBSaver(self.mongo.client, db_name=self.mongo.db.name)
        except Exception:
            self.checkpointer = None

        try:
            mcp_client = MultiServerMCPClient({
                "fetch": {
                    "command": sys.executable,
                    "args": ["-m", "mcp_server_fetch"],
                    "transport": "stdio",
                }
            })
            self.mcp_tools = await mcp_client.get_tools()
        except Exception:
            self.mcp_tools = []

        @tool
        def search_knowledge_base(query: str, config: RunnableConfig) -> str:
            """Search the current company's uploaded knowledge base."""
            retriever = config.get("configurable", {}).get("retriever_instance")
            if retriever is None:
                return (
                    "NO_KB_EVIDENCE: No active company documents are currently indexed. "
                    "The assistant may use general LLM knowledge, but MUST label it with the required disclaimer."
                )
            try:
                docs = retriever.invoke(query)
            except Exception as exc:
                return f"NO_KB_EVIDENCE: Knowledge base search failed: {exc}"
            assistant = config.get("configurable", {}).get("assistant_config") or {}
            citations = assistant.get("citation_requirements") or {}
            formatted = []
            for idx, doc in enumerate(docs, 1):
                filename = doc.metadata.get("source", "Unknown Document")
                raw_page = doc.metadata.get("page")
                chunk_num = doc.metadata.get("chunk")
                try:
                    page_num = int(raw_page) + 1
                except (TypeError, ValueError):
                    page_num = raw_page or "Unknown"
                content = (doc.page_content or "").strip()
                if not content:
                    continue
                lines = [f"[Result {idx}]"]
                if citations.get("enabled", True) and citations.get("include_document_name", True):
                    lines.append(f"Source Document: {filename}")
                if citations.get("enabled", True) and citations.get("include_page", True):
                    lines.append(f"Location Reference: Page {page_num}")
                if citations.get("enabled", True) and citations.get("include_chunk", True) and chunk_num is not None:
                    lines.append(f"Chunk Reference: {chunk_num}")
                lines += [f"Content excerpt:\n{content}", "----------------------------------------"]
                formatted.append("\n".join(lines))
            return "\n\n".join(formatted) if formatted else (
                "NO_KB_EVIDENCE: No relevant company-document passages were found. "
                "The assistant may use general LLM knowledge, but MUST label it with the required disclaimer."
            )

        self.tools = [search_knowledge_base]
        namespace = ("tenants", "{tenant_id}", "users", "{user_id}")
        self.tools.extend([
            create_manage_memory_tool(namespace=namespace),
            create_search_memory_tool(namespace=namespace),
        ])
        self.tools.extend(self.mcp_tools)

        workflow = StateGraph(AgentState)
        workflow.add_node("agent", self.agent_node)
        workflow.add_node("tools", ToolNode(self.tools))
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges("agent", self.should_continue, {"tools": "tools", END: END})
        workflow.add_edge("tools", "agent")

        kwargs = {}
        if self.checkpointer:
            kwargs["checkpointer"] = self.checkpointer
        if self.memory_store:
            kwargs["store"] = self.memory_store
        self.graph = workflow.compile(**kwargs)

    def agent_node(self, state: AgentState, config: RunnableConfig):
        retriever = config.get("configurable", {}).get("retriever_instance")
        assistant = config.get("configurable", {}).get("assistant_config") or {}
        enabled = set(assistant.get("enabled_tools") or ["knowledge_base", "memory", "web_fetch"])
        memory = assistant.get("memory_settings") or {}
        if not memory.get("long_term_memory", True):
            enabled.discard("memory")

        user_message = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None)
        query = extract_text(getattr(user_message, "content", None)) if user_message else ""

        # Fresh retrieval is performed before the model sees the question. This
        # keeps archived/indexing documents out of current-turn evidence.
        if retriever is None or "knowledge_base" not in enabled:
            kb_context = (
                "NO_KB_EVIDENCE: No active company-document evidence is available for this turn. "
                "If answering from general model knowledge, use the required general-knowledge disclaimer."
            )
        else:
            try:
                docs = retriever.invoke(query)
                formatted = []
                for idx, doc in enumerate(docs, 1):
                    filename = doc.metadata.get("source", "Unknown Document")
                    raw_page = doc.metadata.get("page")
                    try:
                        page_num = int(raw_page) + 1
                    except (TypeError, ValueError):
                        page_num = raw_page or "Unknown"
                    content = (doc.page_content or "").strip()
                    if not content:
                        continue
                    formatted.append(
                        f"[KB Result {idx}]\nSource Document: {filename}\nLocation Reference: Page {page_num}\nContent excerpt:\n{content}"
                    )
                kb_context = "\n\n".join(formatted) if formatted else (
                    "NO_KB_EVIDENCE: No relevant company-document passages were found. "
                    "The LLM may answer from general knowledge, but MUST begin with the required disclaimer."
                )
            except Exception as exc:
                kb_context = (
                    f"NO_KB_EVIDENCE: Knowledge-base search failed ({exc}). "
                    "Do not claim document evidence; use general knowledge only with the required disclaimer."
                )

        kb_message = SystemMessage(
            content=(
                "KNOWLEDGE BASE SEARCH RESULT — THIS WAS RETRIEVED BEFORE YOUR ANSWER:\n"
                + kb_context
                + "\n\nUse this evidence first. If it does not actually answer the question, use general model knowledge only with the exact required disclaimer."
            )
        )
        conversation_context = SystemMessage(
            content=(
                "CONVERSATION CONTEXT RULES:\n"
                "- Previous user questions may be used for conversational continuity.\n"
                "- Previous assistant answers, historical tool outputs, and old citations are NOT evidence for the current turn.\n"
                "- Only the fresh KNOWLEDGE BASE SEARCH RESULT for this turn establishes current document evidence.\n"
                "- If a document was archived after an earlier turn, treat it as unavailable for this answer."
            )
        )

        messages = list(state["messages"])
        last_human_index = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), None)
        prior_user_messages = [m for m in messages[:last_human_index] if isinstance(m, HumanMessage)][-8:] if last_human_index is not None else []
        current_turn_messages = messages[last_human_index:] if last_human_index is not None else []

        tool_groups = {
            "search_knowledge_base": "knowledge_base",
            "manage_memory": "memory",
            "search_memory": "memory",
            "fetch": "web_fetch",
        }
        active_tools = [
            tool for tool in self.tools
            if tool_groups.get(getattr(tool, "name", ""), getattr(tool, "name", "")) in enabled
            and not (getattr(tool, "name", "") == "manage_memory" and not memory.get("save_personal_preferences", True))
        ]

        model = ChatOllama(
            model=OLLAMA_LLM_MODEL,
            base_url=OLLAMA_CLOUD_HOST,
            client_kwargs={"headers": {"Authorization": f"Bearer {OLLAMA_API_KEY}"}},
            temperature=0.3,
        )
        response = model.bind_tools(active_tools).invoke(
            [build_system_prompt(assistant), conversation_context, kb_message]
            + prior_user_messages
            + current_turn_messages,
            config=config,
        )
        return {"messages": [response]}

    @staticmethod
    def should_continue(state: AgentState):
        if state["messages"][-1].tool_calls:
            return "tools"
        return END

    async def stream(self, user_query: str, config: dict):
        if self.graph is None:
            raise RuntimeError("Agent is not initialized")
        input_state = {"messages": [HumanMessage(content=user_query)]}
        got_text = False
        yield {"type": "status", "status": "searching_kb", "label": "🔎 Searching knowledge base"}

        async for stream_mode, payload in self.graph.astream(input_state, config=config, stream_mode=["messages", "updates"]):
            if stream_mode == "updates":
                for node_name, node_update in (payload or {}).items():
                    if node_name == "tools":
                        for message in node_update.get("messages", []):
                            tool_name = getattr(message, "name", None)
                            if tool_name:
                                yield {"type": "tool", "tool": tool_name}
                    elif node_name == "agent":
                        yield {"type": "status", "status": "thinking", "label": "Thinking"}
            elif stream_mode == "messages":
                message_chunk, metadata = payload
                if metadata.get("langgraph_node") != "agent":
                    continue
                text = extract_text(getattr(message_chunk, "content", None))
                if text:
                    got_text = True
                    yield {"type": "token", "text": text}

        if not got_text:
            final_state = await self.graph.aget_state(config)
            last_msg = final_state.values["messages"][-1]
            text = extract_text(getattr(last_msg, "content", None))
            if text:
                yield {"type": "token", "text": text}

    def history(self, tenant_id: str, thread_id: str):
        if not self.checkpointer:
            return []
        config = {"configurable": {"thread_id": f"{tenant_id}:{thread_id}"}}
        try:
            checkpoint = self.checkpointer.get_tuple(config)
        except Exception:
            return []
        if not checkpoint:
            return []
        messages = checkpoint.checkpoint.get("channel_values", {}).get("messages", [])
        history = []
        for message in messages:
            text = extract_text(getattr(message, "content", None))
            if not text:
                continue
            if isinstance(message, HumanMessage):
                history.append({"role": "user", "content": text})
            elif isinstance(message, AIMessage):
                history.append({"role": "assistant", "content": text})
        return history

    def delete_history(self, tenant_id: str, thread_id: str):
        if self.checkpointer:
            self.checkpointer.delete_thread(f"{tenant_id}:{thread_id}")
