-- Migration: Enhanced Knowledge Base Management
-- This migration adds source metadata columns to knowledge_base_documents
-- and creates an aggregation view for UI display

-- Phase 1.1: Enhance knowledge_base_documents table
-- Add source metadata columns
ALTER TABLE knowledge_base_documents 
ADD COLUMN IF NOT EXISTS source_type text DEFAULT 'manual';

ALTER TABLE knowledge_base_documents 
ADD COLUMN IF NOT EXISTS source_name text;

ALTER TABLE knowledge_base_documents 
ADD COLUMN IF NOT EXISTS source_url text;

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_kb_docs_source_type 
ON knowledge_base_documents(kb_id, source_type);

CREATE INDEX IF NOT EXISTS idx_kb_docs_source_name 
ON knowledge_base_documents(kb_id, source_name);

-- Phase 1.2: Create aggregation view
CREATE OR REPLACE VIEW vw_kb_sources AS
SELECT 
    kb_id,
    source_type,
    source_name,
    source_url,
    MIN(created_at) as first_added,
    MAX(created_at) as last_updated,
    COUNT(*) as chunk_count,
    SUM(LENGTH(content)) as total_chars,
    -- Generate stable ID from source attributes
    md5(kb_id || COALESCE(source_type,'') || COALESCE(source_name,'') || COALESCE(source_url,''))::uuid as source_id
FROM knowledge_base_documents
WHERE source_name IS NOT NULL
GROUP BY kb_id, source_type, source_name, source_url;

-- Grant appropriate permissions on the view
GRANT SELECT ON vw_kb_sources TO authenticated;
GRANT SELECT ON vw_kb_sources TO service_role; 