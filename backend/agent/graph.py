import asyncio
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


SYSTEM_PROMPT = SystemMessage(
    content=(
        "You are a general-purpose AI assistant for an organization. "
        "You have access to a tenant-specific knowledge base containing documents uploaded by the current company. "
        "You are NOT restricted to HR topics. You can answer technical, business, educational, operational, "
        "programming, documentation, and other questions.\n\n"
        "KNOWLEDGE BASE BEHAVIOR:\n"
        "- When the user's question could be answered by information in the company's uploaded documents, "
        "you MUST call the 'search_knowledge_base' tool before answering.\n"
        "- If the retrieved passages are relevant, use them as the primary source for company/document-specific facts.\n"
        "- If no relevant passages are found, answer using your general model knowledge when you can do so reliably.\n"
        "- If the knowledge base is empty, you may answer from general model knowledge instead of refusing the question.\n"
        "- Never invent, guess, or fabricate a document citation.\n"
        "- Never claim that information came from an uploaded document unless the search tool actually returned it.\n\n"
        "CITATIONS:\n"
        "- Whenever you use information from an uploaded document, cite the exact source document filename and page number "
        "provided by the search tool.\n"
        "- If multiple documents are used, cite each relevant document and page.\n"
        "- For general model knowledge that did not come from the uploaded documents, do not create a fake citation. "
        "When useful, explicitly say that the statement is based on general knowledge.\n\n"
        "SOURCE PRIORITY:\n"
        "- For organization-specific facts, uploaded documents take priority over general model knowledge.\n"
        "- For general facts not covered by the uploaded documents, use your model knowledge.\n"
        "- If the uploaded documents conflict with general knowledge about the organization's own rules, configuration, "
        "procedures, or standards, follow the organization's documents and cite them.\n\n"
        "UNCERTAINTY / HALLUCINATION CONTROL:\n"
        "- If neither the uploaded documents nor your general knowledge provides enough reliable information, say "
        "that you do not know or that there is not enough information to answer reliably.\n"
        "- Do not make up facts simply to provide an answer.\n\n"
        "LONG-TERM MEMORY:\n"
        "- You also have memory tools backed by persistent storage. Use them when relevant to remember durable, "
        "non-sensitive information shared by the user.\n"
        "- Do not store policy/document content as personal memory.\n"
        "- Never store sensitive personal data such as passwords, SSNs, medical details, or financial account information.\n\n"
        "WEB DOCUMENTS:\n"
        "- You have a fetch tool for URLs supplied by the user. Use it when the user asks about a specific URL or "
        "online document that is not available in the tenant knowledge base. Tell the user when information came from "
        "the fetched URL.\n"
        "Answer naturally and helpfully. Do not describe yourself as an HR assistant unless the user explicitly asks "
        "about an HR-specific role."
    )
)


class AgentService:
    def __init__(self, qdrant_service, mongo_service):
        self.qdrant = qdrant_service
        self.mongo = mongo_service
        self.memory_store = None
        self.checkpointer = None
        self.graph = None
        self.mcp_tools = []
        self.tools = []

    async def initialize(self):
        from ..memory.qdrant_store import QdrantMemoryStore
        from ..config import (
            QDRANT_MEMORY_COLLECTION,
            MEMORY_EMBEDDING_DIMS,
            MAX_NAMESPACE_DEPTH,
        )
        self.memory_store = QdrantMemoryStore(
            client=self.qdrant.client,
            collection_name=QDRANT_MEMORY_COLLECTION,
            embeddings=self.qdrant.embeddings,
            dims=MEMORY_EMBEDDING_DIMS,
            max_namespace_depth=MAX_NAMESPACE_DEPTH,
        )

        try:
            from langgraph.checkpoint.mongodb import MongoDBSaver
            self.checkpointer = MongoDBSaver(
                self.mongo.client,
                db_name=self.mongo.db.name,
            )
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
            """
            Search the current company's uploaded knowledge base for passages
            relevant to the user's question. Results include source filenames
            and page numbers for citations.
            """
            retriever = config.get("configurable", {}).get("retriever_instance")
            if retriever is None:
                return (
                    "No company documents are currently indexed. "
                    "There is no document evidence for this question; "
                    "the assistant may use general model knowledge."
                )

            try:
                docs = retriever.invoke(query)
            except Exception as exc:
                return f"Knowledge base search failed: {exc}"

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
                    f"[Result {idx}]\n"
                    f"Source Document: {filename}\n"
                    f"Location Reference: Page {page_num}\n"
                    f"Content excerpt:\n{content}\n"
                    f"----------------------------------------"
                )

            return (
                "\n\n".join(formatted)
                if formatted
                else "No relevant company-document passages were found."
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
        workflow.add_conditional_edges(
            "agent",
            self.should_continue,
            {"tools": "tools", END: END},
        )
        workflow.add_edge("tools", "agent")

        kwargs = {}
        if self.checkpointer:
            kwargs["checkpointer"] = self.checkpointer
        if self.memory_store:
            kwargs["store"] = self.memory_store

        self.graph = workflow.compile(**kwargs)

    def agent_node(self, state: AgentState, config: RunnableConfig):
        model = ChatOllama(
            model=OLLAMA_LLM_MODEL,
            base_url=OLLAMA_CLOUD_HOST,
            client_kwargs={"headers": {"Authorization": f"Bearer {OLLAMA_API_KEY}"}},
            temperature=0.3,
        )
        response = model.bind_tools(self.tools).invoke(
            [SYSTEM_PROMPT] + list(state["messages"]),
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

        async for stream_mode, payload in self.graph.astream(
            input_state,
            config=config,
            stream_mode=["messages", "updates"],
        ):
            if stream_mode == "updates":
                for node_name, node_update in (payload or {}).items():
                    if node_name != "tools":
                        continue
                    for message in node_update.get("messages", []):
                        tool_name = getattr(message, "name", None)
                        if tool_name:
                            yield {
                                "type": "tool",
                                "tool": tool_name,
                            }

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
