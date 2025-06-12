# Implementation Plan – Supabase Vector DB + Contextual RAG

**Objective (v2):** Migrate the knowledge-base layer **entirely** to Supabase Vector + OpenAI embeddings (Contextual Retrieval & optional Cohere reranking).  ChromaDB will be removed from the code-base and container. *No* public FastAPI route or response shape changes.

---

## 0.  Environment & API Keys

| Variable | Purpose | Required |
|----------|---------|----------|
| `SUPABASE_URL` | Supabase project REST URL | ✅ |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-side key (bypasses RLS) | ✅ |
| `OPENAI_API_KEY` | Generates context summaries / LLM responses | ⚙️ |
| `COHERE_API_KEY` | Cohere **Embeddings** (primary) & optional reranker | ✅ |
| `ANTHROPIC_API_KEY` | Anthropic Claude key for context generation (mandatory for Contextual Retrieval) | ✅ |

> Keys marked ✅ are required. `COHERE_API_KEY` is optional—add it to enable the reranking enhancement.

---

## 1.  Supabase Schema (run once)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_bases (
  kb_id TEXT PRIMARY KEY,
  name  TEXT,
  agent_name TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE knowledge_base_documents (
  id          UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
  kb_id       TEXT         REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
  document_id TEXT         NOT NULL,
  content     TEXT         NOT NULL,
  ctx_text    TEXT         NOT NULL,                -- contextualised chunk
  embedding   vector(1536) NOT NULL,
  metadata    JSONB        DEFAULT '{}',
  created_at  TIMESTAMPTZ  DEFAULT now()
);

-- Indexes
CREATE INDEX ivfflat_embedding ON knowledge_base_documents
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX gin_ctx_tsv ON knowledge_base_documents
  USING GIN (to_tsvector('english', ctx_text));
```

---

## 2.  Python Modules to Add / Modify

| File | Purpose |
|------|---------|
| `app/core/embeddings.py` | Cohere embedding wrapper (batch-aware) |
| `app/core/contextualizer.py` | Generates 50-100-token context for each chunk using OpenAI (or Claude if key present) + LRU prompt cache |
| `app/core/supabase_kb_manager.py` | KBManager implementation that reads/writes Supabase |
| `app/core/kb_manager_factory.py` | Thin re-export: `from .supabase_kb_manager import kb_manager` – keeps import path stable |

Refactor imports in `main.py`, `tools.py`, route files, etc. to:
```python
from app.core.kb_manager_factory import kb_manager
```

---

## 3.  Hybrid Retrieval SQL Function

Create RPC `hybrid_search` combining BM25 & vector similarity (see code appendix). Weight 0.55 vector / 0.45 BM25.

---

## 4.  Ingestion Flow (file uploads, JSON, scrape)

1. Parse / chunk text (existing `data_processor.chunk_text`).
2. `ctx = contextualizer.create_context(full_doc, chunk)`.
3. `ctx_text = f"{ctx} {chunk}"`.
4. Embed `ctx_text` via Cohere's `embed-english-v3` ➜ 768-dim vector.
5. Insert row into `knowledge_base_documents`.

Batch ≤ 96 chunks/request; cache identical contexts to cut cost 90 % (as recommended by Anthropic[1]).

---

## 5.  Query Flow

```text
User → /agents/{kb}/chat → kb_manager.get_similar_docs()
       └─ embed query
       └─ call RPC hybrid_search
       └─ (optional) rerank top-N via **Cohere**
       └─ return K chunks → LangChain agent
```

No change to endpoint inputs/outputs.

---

## 6.  Migration Steps

1. Merge Supabase manager code and delete `app/core/kb_manager.py` plus all Chroma-specific utilities.  
2. Remove `chromadb`, `sentence-transformers`, FAISS etc. from **requirements.txt** and the Dockerfile.  
3. Apply the Supabase schema (Section 1) and `hybrid_search` RPC.  
4. **Back-fill**: one-off script iterates through existing Chroma collections, embeds, and inserts into Supabase.  
5. Deploy – all routes now use Supabase automatically (no feature flag).  
6. Validate with contract tests; monitor `/health` which now returns `{vector_impl: "supabase"}`.  
7. After verification, delete the `./chromadb_data` volume from *docker-compose.yml* and remove any residual code paths.

---

## 7.  Monitoring / QA

• Prometheus/Grafana: query latency, insert latency, OpenAI tokens.  
• Contract test suite executed in CI for both flag states.  
• Health endpoint returns `{vector_impl: "supabase"}` for quick debugging.

---

## 8.  Post-launch Enhancements

* Add SHA-256 duplicate guard unique index.  
* Nightly job `cleanup_duplicates` (already implemented).  
* If reranking is enabled, monitor quality metrics (Cohere) and reassess thresholds.  
* Tune ivfflat `lists` / query `probes` per KB size.

---

### Appendix – References

* [1] Anthropic – "Introducing Contextual Retrieval", 2024-09-19. <https://www.anthropic.com/news/contextual-retrieval> 