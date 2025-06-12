-- Enable vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create knowledge_bases table
CREATE TABLE IF NOT EXISTS knowledge_bases (
  kb_id TEXT PRIMARY KEY,
  name  TEXT,
  agent_name TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Create knowledge_base_documents table with 768-dim vectors for Cohere
CREATE TABLE IF NOT EXISTS knowledge_base_documents (
  id          UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
  kb_id       TEXT         REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
  document_id TEXT         NOT NULL,
  content     TEXT         NOT NULL,
  ctx_text    TEXT         NOT NULL,                -- contextualised chunk
  embedding   vector(768)  NOT NULL,                -- Cohere embed-english-v3.0 produces 768 dimensions
  metadata    JSONB        DEFAULT '{}',
  created_at  TIMESTAMPTZ  DEFAULT now()
);

-- Create indexes for efficient retrieval
CREATE INDEX IF NOT EXISTS ivfflat_embedding ON knowledge_base_documents
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS gin_ctx_tsv ON knowledge_base_documents
  USING GIN (to_tsvector('english', ctx_text));

-- Create hybrid search function combining vector similarity and BM25
CREATE OR REPLACE FUNCTION hybrid_search(
  kb_id_param TEXT,
  query_text TEXT,
  query_embedding vector(768),
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
      id,
      document_id,
      content,
      ctx_text,
      1 - (embedding <=> query_embedding) AS similarity_score
    FROM knowledge_base_documents
    WHERE kb_id = kb_id_param
    ORDER BY embedding <=> query_embedding
    LIMIT match_count * 2
  ),
  keyword_search AS (
    SELECT 
      id,
      document_id,
      content,
      ctx_text,
      ts_rank_cd(to_tsvector('english', ctx_text), plainto_tsquery('english', query_text)) AS rank_score
    FROM knowledge_base_documents
    WHERE kb_id = kb_id_param
      AND to_tsvector('english', ctx_text) @@ plainto_tsquery('english', query_text)
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

-- Add content hash index to prevent duplicates (optional, for post-launch enhancement)
-- CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_content_hash ON knowledge_base_documents(kb_id, digest(content, 'sha256')); 