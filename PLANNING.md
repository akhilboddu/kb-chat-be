# PLANNING.md: Multi-Tenant AI Sales Agent Backend + Test UI (v1 - WebSocket Chat)

**Target AI Model for Coding:** Gemini 2.5 Pro

**Project Goal:** Develop a Python backend service (FastAPI) for a multi-tenant AI sales agent system (real-time WebSocket chat, RAG from JSON-created KBs using DeepSeek LLM, handoff, KB updates) **and** a simple HTML/CSS/JS UI for testing/interaction.

---

## Phase 1: Backend Setup and Core Components

* [ ] **1.1 Environment Setup:**
    * [ ] Create Python virtual environment.
    * [ ] Install required libraries: `fastapi`, `uvicorn[standard]`, `langchain`, `langchain-agents`, `langchain-community`, `sentence-transformers`, `chromadb-client`, `python-dotenv`, Client/library for DeepSeek integration (specific DeepSeek SDK).
    * [ ] Set up `.env` file (ChromaDB path, DeepSeek config/API keys).
    * [ ] Implement `config.py` to load settings.
    * [ ] Initialize ChromaDB client (`chromadb.PersistentClient`).
    * [ ] Initialize embedding function (`HuggingFaceEmbeddings`).
    * [ ] Initialize LangChain LLM object for DeepSeek integration.

* [ ] **`1.2 Data Processing Module (data_processor.py):`**
    * [ ] Implement `extract_text_from_json(data: dict) -> str` (Parse JSON, extract relevant text).
    * [ ] Implement `chunk_text(text: str) -> List[str]` (Chunk text using `RecursiveCharacterTextSplitter`).

* [ ] **`1.3 Multi-Tenant KB Management Module (kb_manager.py):`**
    * [ ] Implement `create_or_get_kb(kb_id: str, embedding_function) -> Collection` (Get/Create ChromaDB collection per `kb_id`).
    * [ ] Implement `populate_kb(kb_collection: Collection, text_chunks: List[str], embedding_function) -> None` (Embed & add chunks to collection).
    * [ ] Implement `add_to_kb(kb_collection: Collection, text_to_add: str, embedding_function) -> None` (Add single text update to collection).

## Phase 2: Backend Agent Tools Implementation

* [ ] **`2.1 KB-Specific Tool Generation (tools.py):`**
    * [ ] Implement `get_retriever_tool(kb_collection: Collection) -> Tool` (Create retriever tool for the specific collection).
    * [ ] Implement `get_answering_tool(llm) -> Tool` (Create tool using DeepSeek LLM to generate answer from query + context).
    * [ ] Implement `get_knowledge_update_tool(kb_collection: Collection, embedding_function) -> Tool` (Create tool wrapping `kb_manager.add_to_kb`).

## Phase 3: Backend Agent and API/WebSocket Implementation

* [ ] **3.1 LLM Initialization:** (Ensure DeepSeek LLM object from 1.1 is accessible).
* [ ] **`3.2 Agent Configuration (agent_manager.py):`**
    * [ ] Implement `create_agent_executor(kb_id: str, llm)`:
        * [ ] Get specific `kb_collection`.
        * [ ] Create KB-specific `retriever_tool` and generic `answering_tool`.
        * [ ] Define agent prompt (ReAct style, persona, tools, handoff signal "HANDOFF_REQUIRED").
        * [ ] Create and return `AgentExecutor`.

* [ ] **`3.3 API Endpoints & WebSocket (main.py):`**
    * [ ] Initialize FastAPI app instance.
    * [ ] Implement `POST /agents` (HTTP):
        * [ ] Define request body model (Pydantic).
        * [ ] Generate `kb_id`.
        * [ ] Call `data_processor.extract_text_from_json`, `data_processor.chunk_text`.
        * [ ] Call `kb_manager.create_or_get_kb`, `kb_manager.populate_kb`.
        * [ ] Return `kb_id` and status. Implement error handling.
    * [ ] Implement `WS /ws/agents/{kb_id}/chat` (WebSocket):
        * [ ] Define WebSocket endpoint function `async def websocket_endpoint(...)`.
        * [ ] Accept connection.
        * [ ] Instantiate `AgentExecutor` via `agent_manager.create_agent_executor`.
        * [ ] Implement message receiving loop (`websocket.receive_text`/`receive_json`).
        * [ ] Invoke agent asynchronously (`agent_executor.ainvoke`).
        * [ ] Parse response, check for "HANDOFF_REQUIRED".
        * [ ] Send `{"type": "answer", ...}` or `{"type": "handoff", ...}` via `websocket.send_json`.
        * [ ] Handle `WebSocketDisconnect` and other exceptions.
    * [ ] Implement `POST /agents/{kb_id}/human_response` (HTTP):
        * [ ] Define request body model (Pydantic).
        * [ ] If update flag is true, call KB update logic (`kb_manager.add_to_kb`).
        * [ ] Return status confirmation. Implement error handling.

## Phase 4: Backend Testing and Refinement

* [ ] **4.1 API & WebSocket Testing:**
    * [ ] Test HTTP endpoints (`/agents`, `/human_response`) via API testing tools.
    * [ ] Test WebSocket endpoint (`/ws/.../chat`) via WebSocket clients/scripts. Verify connection, message types (`answer`/`handoff`), KB isolation.
* [ ] **4.2 Refinement:** (Tune prompts, chunking strategy, error handling based on testing).

## Phase 5: Simple Test UI Development (HTML/CSS/JS)

* [ ] **`5.1 HTML Structure (index.html):`**
    * [ ] Create main container and sections (KB Creation, Chat Interface, Handoff).
    * [ ] Add input fields (`kb_name`, `json_data`, `kb_id`, `chat_input`, `human_response`).
    * [ ] Add text areas (`json_data`, `human_response`).
    * [ ] Add buttons (`create-kb-btn`, `connect-btn`, `disconnect-btn`, `send-btn`, `submit-human-response-btn`).
    * [ ] Add display areas (`kb-status`, `connection-status`, `chat-output`, `handoff-query`, `handoff-status`).
    * [ ] Add checkbox (`update-kb-checkbox`).
    * [ ] Include CDN link for Tailwind CSS in `<head>`.
* [ ] **5.2 Styling (Tailwind CSS):**
    * [ ] Apply Tailwind classes for layout, spacing, typography, borders, colors.
    * [ ] Style buttons, inputs, chat messages.
    * [ ] Ensure basic responsiveness.
* [ ] **``5.3 JavaScript Logic (index.html <script> tag):``**
    * [ ] Define API/WebSocket base URLs.
    * [ ] Get references to all necessary DOM elements.
    * [ ] Implement `addChatMessage` function.
    * [ ] Implement `updateConnectionState` function.
    * [ ] **KB Creation Logic:** Event listener, `fetch` call to `POST /agents`, handle response.
    * [ ] **WebSocket Logic:** Event listeners for Connect/Disconnect/Send, `WebSocket` object creation, `onopen`/`onmessage`/`onerror`/`onclose` handlers, handle `handoff` message type.
    * [ ] **Handoff Logic:** Event listener for Submit, `fetch` call to `POST /.../human_response`, handle response.
* [ ] **5.4 UI Testing:**
    * [ ] Test KB creation, WebSocket connection, chat send/receive, handoff flow, KB update checkbox via UI.
    * [ ] Test basic error display in UI.

---