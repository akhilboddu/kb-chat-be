-- Add knowledge_source column to track the origin of each document chunk
ALTER TABLE knowledge_base_documents 
ADD COLUMN IF NOT EXISTS knowledge_source TEXT;

-- Add an index for efficient filtering by source
CREATE INDEX IF NOT EXISTS idx_kb_source ON knowledge_base_documents(kb_id, knowledge_source);

-- Update existing records to have a default source (can be updated later)
UPDATE knowledge_base_documents 
SET knowledge_source = 'unknown' 
WHERE knowledge_source IS NULL;

-- Add a comment to document the column
COMMENT ON COLUMN knowledge_base_documents.knowledge_source IS 'Source of the document chunk: website, file, human conversation, manual, etc.'; 