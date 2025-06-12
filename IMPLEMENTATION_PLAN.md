# Implementation Plan – Supabase Vector DB + Contextual RAG

**Objective (v2):** Migrate the knowledge-base layer **entirely** to Supabase Vector + ~~OpenAI~~ **Cohere** embeddings (Contextual Retrieval & optional Cohere reranking).  ChromaDB will be removed from the code-base and container. *No* public FastAPI route or response shape changes.

**Progress:** Steps 1-6 ✅ | Step 7 🔄 | Steps 8-11 📋

---

## 0.  Environment & API Keys

| Variable | Purpose | Required | Status |
|----------|---------|----------|--------|
| `SUPABASE_URL` | Supabase project REST URL | ✅ | Ready |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-side key (bypasses RLS) | ✅ | Ready |
| `OPENAI_API_KEY` | Generates context summaries / LLM responses | ✅ | Ready |
| `COHERE_API_KEY` | Cohere **Embeddings** (primary) & optional reranker | ✅ | Ready |
| `ANTHROPIC_API_KEY` | Anthropic Claude key for context generation (mandatory for Contextual Retrieval) | ✅ | Ready |

> All keys marked ✅ are required. Cohere is used for both embeddings and optional reranking.

---

## 1.  Supabase Schema (run once) ✅ COMPLETED

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
  embedding   vector(1024) NOT NULL,                -- Cohere embed-english-v3.0 produces 1024 dimensions
  metadata    JSONB        DEFAULT '{}',
  created_at  TIMESTAMPTZ  DEFAULT now()
);

-- Indexes
CREATE INDEX ivfflat_embedding ON knowledge_base_documents
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX gin_ctx_tsv ON knowledge_base_documents
  USING GIN (to_tsvector('english', ctx_text));
```

**Status:** ✅ Schema applied, tables created, indexes active

---

## 2.  Python Modules to Add / Modify

| File | Purpose | Status |
|------|---------|--------|
| `app/core/embeddings.py` | Cohere embedding wrapper (batch-aware) | ✅ DONE |
| `app/core/contextualizer.py` | Generates 50-100-token context for each chunk using ~~OpenAI~~ **Anthropic** (or OpenAI fallback) + LRU prompt cache | ✅ DONE |
| `app/core/supabase_kb_manager.py` | KBManager implementation that reads/writes Supabase | 🔄 TODO |
| `app/core/kb_manager_factory.py` | Thin re-export: `from .supabase_kb_manager import kb_manager` – keeps import path stable | 🔄 TODO |

Refactor imports in `main.py`, `tools.py`, route files, etc. to:
```python
from app.core.kb_manager_factory import kb_manager
```

---

## 3.  Hybrid Retrieval SQL Function ✅ COMPLETED

Create RPC `hybrid_search` combining BM25 & vector similarity (see code appendix). Weight 0.55 vector / 0.45 BM25.

```sql
CREATE OR REPLACE FUNCTION hybrid_search(
  kb_id_param TEXT,
  query_text TEXT,
  query_embedding vector(1024),
  match_count INT DEFAULT 10
)
RETURNS TABLE (
  id UUID,
  document_id TEXT,
  content TEXT,
  ctx_text TEXT,
  score FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  WITH semantic_search AS (
    SELECT 
      kd.id,
      kd.document_id,
      kd.content,
      kd.ctx_text,
      1 - (kd.embedding <=> query_embedding) AS similarity_score
    FROM knowledge_base_documents kd
    WHERE kd.kb_id = kb_id_param
    ORDER BY kd.embedding <=> query_embedding
    LIMIT match_count * 2
  ),
  keyword_search AS (
    SELECT 
      kd.id,
      kd.document_id,
      kd.content,
      kd.ctx_text,
      ts_rank_cd(to_tsvector('english', kd.ctx_text), plainto_tsquery('english', query_text)) AS rank_score
    FROM knowledge_base_documents kd
    WHERE kd.kb_id = kb_id_param
      AND to_tsvector('english', kd.ctx_text) @@ plainto_tsquery('english', query_text)
    ORDER BY rank_score DESC
    LIMIT match_count * 2
  )
  SELECT 
    COALESCE(s.id, k.id) AS id,
    COALESCE(s.document_id, k.document_id) AS document_id,
    COALESCE(s.content, k.content) AS content,
    COALESCE(s.ctx_text, k.ctx_text) AS ctx_text,
    (COALESCE(s.similarity_score, 0) * 0.55 + COALESCE(k.rank_score, 0) * 0.45) AS score
  FROM semantic_search s
  FULL OUTER JOIN keyword_search k ON s.id = k.id
  ORDER BY score DESC
  LIMIT match_count;
END;
$$;
```

**Status:** ✅ Function created and tested with proper column aliasing

---

## 4.  Ingestion Flow (file uploads, JSON, scrape)

1. Parse / chunk text (existing `data_processor.chunk_text`).
2. `ctx = contextualizer.create_context(full_doc, chunk)`.
3. `ctx_text = f"{ctx} {chunk}"`.
4. Embed `ctx_text` via Cohere's `embed-english-v3` ➜ 1024-dim vector.
5. Insert row into `knowledge_base_documents`.

Batch ≤ 96 chunks/request; cache identical contexts to cut cost 90 % (as recommended by Anthropic[1]).

**Status:** 🔄 Components ready, integration pending

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

**Status:** 🔄 To be implemented in supabase_kb_manager.py

---

## 6.  Migration Steps

### Completed ✅
1. ~~Merge Supabase manager code and delete `app/core/kb_manager.py` plus all Chroma-specific utilities.~~ **Partially done - dependencies updated**
2. ✅ Remove `chromadb`, `sentence-transformers`, ~~FAISS~~ etc. from **requirements.txt** and the Dockerfile.  
3. ✅ Apply the Supabase schema (Section 1) and `hybrid_search` RPC.

### In Progress 🔄
4. ✅ **Create Supabase KB Manager**: Implement `app/core/supabase_kb_manager.py`
5. ✅ **Create Factory Module**: Implement `app/core/kb_manager_factory.py`
6. **Update Imports**: Refactor all imports to use the factory module (Next step)

### TODO 📋
7. **Remove ChromaDB Code**: Delete `app/core/kb_manager.py` and ChromaDB references
8. **Back-fill**: one-off script iterates through existing Chroma collections, embeds, and inserts into Supabase.  
9. Deploy – all routes now use Supabase automatically (no feature flag).  
10. Validate with contract tests; monitor `/health` which now returns `{vector_impl: "supabase"}`.  
11. After verification, delete the `./chromadb_data` volume from *docker-compose.yml* and remove any residual code paths.

---

## 7.  Monitoring / QA

• Prometheus/Grafana: query latency, insert latency, OpenAI tokens.  
• Contract test suite executed in CI for both flag states.  
• Health endpoint returns `{vector_impl: "supabase"}` for quick debugging.

**Status:** 🔄 To be implemented

---

## 8.  Post-launch Enhancements

* Add SHA-256 duplicate guard unique index.  
* Nightly job `cleanup_duplicates` (already implemented).  
* If reranking is enabled, monitor quality metrics (Cohere) and reassess thresholds.  
* Tune ivfflat `lists` / query `probes` per KB size.

---

## Progress Summary

### ✅ Completed (Steps 1-6)
- **Dependencies**: Removed ChromaDB, added Cohere and Anthropic
- **Docker**: Updated Dockerfile and docker-compose.yml
- **Supabase Schema**: Tables, indexes, and hybrid_search function created
- **Embeddings Module**: Cohere wrapper with batching and retry logic
- **Contextualizer Module**: Anthropic Claude with OpenAI fallback and LRU caching
- **Supabase KB Manager**: Complete implementation with all KBManager methods
- **Factory Module**: Created for seamless backward compatibility

### 🔄 In Progress (Step 7)
- **Update Imports**: Refactor all imports to use the factory module

### 📋 Remaining (Steps 8-11)
- Remove all ChromaDB code
- Migration script for existing data
- End-to-end testing
- Deployment and monitoring
- Documentation updates

### 🎯 Next Steps
1. Implement `app/core/supabase_kb_manager.py` with all KBManager methods
2. Create `app/core/kb_manager_factory.py` for backward compatibility
3. Update all imports across the codebase
4. Test the complete flow
5. Deploy and monitor

---

### Appendix – References

* [1] Anthropic – "Introducing Contextual Retrieval", 2024-09-19. <https://www.anthropic.com/news/contextual-retrieval> 