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


HR_SYSTEM_PROMPT = SystemMessage(
    content=(
        "You are an expert corporate HR Assistant with access to documents uploaded by the user. "
        "Your job is to answer user queries using the 'query_hr_policies' tool. "
        "CRITICAL RULE: For every piece of information or policy detail you supply, you must explicitly "
        "cite the 'Source Document' filename AND the exact 'Location Reference' page number. "
        "If an answer requires checking multiple documents, combine the facts and provide clean citations for each.\n\n"
        "LONG-TERM MEMORY: You also have 'manage_memory' and 'search_memory' tools backed by persistent "
        "storage that survives across separate conversations with this same employee. "
        "Use 'search_memory' early in a conversation (or whenever it could help) to recall relevant facts "
        "you've learned before, such as the employee's name, role, department, or recurring concerns. "
        "Use 'manage_memory' to save durable, useful facts the employee shares about themselves or their "
        "situation — not the policy content itself (that lives in the documents), and not transient small talk. "
        "Never store sensitive personal data (e.g. SSNs, medical details, salary figures) in memory."
        "MANDATORY MEMORY RULE: Whenever the user shares any personal fact about "
        "themselves (their name, role, department, team, preferences, or recurring concerns), you MUST immediately "
        "call the 'manage_memory' tool to save it BEFORE responding to them.\n"
        "WEB DOCUMENTS: You also have a 'fetch' tool that retrieves the contents of "
        "any URL the user provides. Use it when the user references a link or asks about content that isn't "
        "in the uploaded PDF knowledge base. Always tell the user which URL you pulled information from."
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
        def query_hr_policies(query: str, config: RunnableConfig) -> str:
            """Queries corporate policy documents to find accurate facts, page numbers, and source filenames."""
            retriever = config.get("configurable", {}).get("retriever_instance")
            if retriever is None:
                return "Error: No policy knowledge base is available. Upload and build the knowledge base first."

            docs = retriever.invoke(query)
            formatted = []
            for idx, doc in enumerate(docs, 1):
                filename = doc.metadata.get("source", "Unknown Policy")
                page_num = doc.metadata.get("page", 0) + 1
                content = doc.page_content.strip()
                formatted.append(
                    f"[Result {idx}]\n"
                    f"Source Document: {filename}\n"
                    f"Location Reference: Page {page_num}\n"
                    f"Content excerpt:\n{content}\n"
                    f"----------------------------------------"
                )
            return "\n\n".join(formatted) or "No matching policy passages were found."

        self.tools = [query_hr_policies]
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
            [HR_SYSTEM_PROMPT] + list(state["messages"]),
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
