# End-to-End Testing Guide - Supabase Vector DB Migration

## 🎯 Overview
This guide provides step-by-step instructions to test the new Supabase Vector DB implementation with Contextual RAG. Follow these tests to ensure the migration is working correctly.

## 📋 Prerequisites

### 1. Environment Variables
Ensure all required environment variables are set in your `.env` file:

```bash
# Supabase (Backend Vector DB)
SUPABASE_URL=your_supabase_project_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key  # NOT the anon key

# Embeddings & Context
COHERE_API_KEY=your_cohere_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key  # For context generation
OPENAI_API_KEY=your_openai_api_key  # Fallback for context

# LLM (at least one required)
GOOGLE_API_KEY=your_google_api_key  # For Gemini
# or
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4
```

### 2. Verify Supabase Schema
Run these SQL queries in your Supabase SQL editor to verify the schema:

```sql
-- Check if tables exist
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN ('knowledge_bases', 'knowledge_base_documents');

-- Check if vector extension is enabled
SELECT * FROM pg_extension WHERE extname = 'vector';

-- Check if hybrid_search function exists
SELECT routine_name FROM information_schema.routines 
WHERE routine_schema = 'public' 
AND routine_name = 'hybrid_search';
```

## 🧪 Test Cases

### Test 1: Server Startup & Health Check

1. **Start the server:**
   ```bash
   python3 app/main.py
   ```

2. **Expected output:**
   ```
   LLM: Initialized Google Gemini Pro (gemini-2.0-flash-lite)
   Configuration loaded.
   SQLite DB Path: ./db/kb_metadata.sqlite
   Initialized Supabase KB Manager with Contextual RAG
   ```

3. **Test health endpoint:**
   ```bash
   curl http://localhost:8000/health
   ```
   
   **Expected:** `{"status":"healthy"}`

### Test 2: Create a New Agent (Knowledge Base)

1. **Create unnamed agent:**
   ```bash
   curl -X POST http://localhost:8000/agents \
     -H "Content-Type: application/json"
   ```

2. **Create named agent:**
   ```bash
   curl -X POST http://localhost:8000/agents \
     -H "Content-Type: application/json" \
     -d '{"name": "Test Agent E2E"}'
   ```

   **Expected response:**
   ```json
   {
     "kb_id": "kb_1234567890_abcdefgh",
     "name": "Test Agent E2E",
     "message": "Agent created successfully with an empty knowledge base."
   }
   ```

3. **Save the `kb_id` for next tests!**

### Test 3: Populate KB with JSON Data

1. **Add test data to the KB:**
   ```bash
   curl -X POST http://localhost:8000/agents/{kb_id}/json \
     -H "Content-Type: application/json" \
     -d '{
       "json_data": {
         "company": "Acme Corp",
         "products": [
           {
             "name": "Widget Pro",
             "description": "Our flagship widget with advanced features including AI integration and cloud connectivity.",
             "price": "$299"
           },
           {
             "name": "Widget Lite",
             "description": "Entry-level widget perfect for small businesses and personal use.",
             "price": "$99"
           }
         ],
         "support": {
           "email": "support@acme.com",
           "phone": "1-800-WIDGETS",
           "hours": "24/7 customer support available"
         }
       }
     }'
   ```

   **Expected:** Success response with status "success"

### Test 4: Query the Knowledge Base

1. **Test semantic search:**
   ```bash
   curl -X POST http://localhost:8000/agents/{kb_id}/chat \
     -H "Content-Type: application/json" \
     -d '{
       "message": "What products do you offer?",
       "user_id": "test_user_123"
     }'
   ```

2. **Test specific query:**
   ```bash
   curl -X POST http://localhost:8000/agents/{kb_id}/chat \
     -H "Content-Type: application/json" \
     -d '{
       "message": "Tell me about the AI features in your products",
       "user_id": "test_user_123"
     }'
   ```

3. **Test support query:**
   ```bash
   curl -X POST http://localhost:8000/agents/{kb_id}/chat \
     -H "Content-Type: application/json" \
     -d '{
       "message": "How can I contact support?",
       "user_id": "test_user_123"
     }'
   ```

### Test 5: File Upload Test

1. **Create a test text file:**
   ```bash
   echo "This is a test document about our new quantum computing service. 
   It offers unprecedented processing power for complex calculations.
   Available starting at $999/month with 24/7 support." > test_doc.txt
   ```

2. **Upload the file:**
   ```bash
   curl -X POST http://localhost:8000/file/upload \
     -F "file=@test_doc.txt" \
     -F "kb_id={kb_id}"
   ```

3. **Query about the uploaded content:**
   ```bash
   curl -X POST http://localhost:8000/agents/{kb_id}/chat \
     -H "Content-Type: application/json" \
     -d '{
       "message": "What is the quantum computing service?",
       "user_id": "test_user_123"
     }'
   ```

### Test 6: List and Inspect KBs

1. **List all knowledge bases:**
   ```bash
   curl http://localhost:8000/agents
   ```

2. **Get KB content:**
   ```bash
   curl "http://localhost:8000/agents/{kb_id}/content?limit=10"
   ```

### Test 7: Web Scraping Test

1. **Scrape a webpage:**
   ```bash
   curl -X POST http://localhost:8000/scrape \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://example.com",
       "kb_id": "{kb_id}"
     }'
   ```

### Test 8: Performance & Quality Tests

1. **Test response time for queries:**
   ```bash
   time curl -X POST http://localhost:8000/agents/{kb_id}/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "What are your products?", "user_id": "test_user"}'
   ```

2. **Test with complex queries:**
   - Ask about specific details that require context understanding
   - Ask questions that combine multiple pieces of information
   - Test edge cases (empty queries, very long queries)

### Test 9: Clean Up

1. **Delete test KB:**
   ```bash
   curl -X DELETE http://localhost:8000/agents/{kb_id}
   ```

## 🔍 Verification Checklist

### Backend Supabase Verification
Run these checks in your Supabase SQL editor:

1. **Check KB was created:**
   ```sql
   SELECT * FROM knowledge_bases WHERE kb_id = 'your_test_kb_id';
   ```

2. **Check documents were added:**
   ```sql
   SELECT 
     id,
     kb_id,
     document_id,
     LEFT(content, 100) as content_preview,
     LEFT(ctx_text, 100) as context_preview,
     created_at
   FROM knowledge_base_documents 
   WHERE kb_id = 'your_test_kb_id'
   ORDER BY created_at DESC;
   ```

3. **Verify embeddings exist:**
   ```sql
   SELECT 
     id,
     document_id,
     embedding IS NOT NULL as has_embedding,
     array_length(embedding::real[], 1) as embedding_dimensions
   FROM knowledge_base_documents 
   WHERE kb_id = 'your_test_kb_id'
   LIMIT 5;
   ```
   
   **Expected:** `has_embedding = true` and `embedding_dimensions = 768`

4. **Test hybrid search directly:**
   ```sql
   SELECT * FROM hybrid_search(
     'your_test_kb_id',
     'AI features',
     (SELECT embedding FROM knowledge_base_documents WHERE kb_id = 'your_test_kb_id' LIMIT 1),
     5
   );
   ```

## 📊 Performance Benchmarks

Track these metrics:

1. **Query Response Time:**
   - Target: < 2 seconds for simple queries
   - Target: < 5 seconds for complex queries with context

2. **Embedding Generation:**
   - Cohere embedding: ~100-200ms per chunk
   - Context generation: ~500ms-1s per chunk (with caching)

3. **Search Quality:**
   - Relevant results should appear in top 3-5 results
   - Context should improve retrieval accuracy

## 🐛 Troubleshooting

### Common Issues:

1. **"No documents found" errors:**
   - Check if KB exists in Supabase
   - Verify embeddings were generated
   - Check Supabase connection

2. **Slow responses:**
   - Check if context caching is working
   - Monitor API rate limits (Cohere, Anthropic)
   - Check Supabase query performance

3. **Import errors:**
   - Ensure all dependencies are installed: `pip install -r requirements.txt`
   - Check environment variables are set

### Debug Commands:

1. **Check logs in real-time:**
   ```bash
   tail -f app.log  # If logging to file
   ```

2. **Test Supabase connection:**
   ```python
   from app.core.supabase_client import supabase
   print(supabase.table('knowledge_bases').select('*').limit(1).execute())
   ```

3. **Test embeddings:**
   ```python
   from app.core.embeddings import embeddings_manager
   test_embedding = embeddings_manager.embed_query("test query")
   print(f"Embedding shape: {len(test_embedding)}")  # Should be 768
   ```

## ✅ Success Criteria

The migration is successful if:

1. ✅ All API endpoints work without errors
2. ✅ Search results are relevant and include contextual information
3. ✅ Response times are acceptable (< 5s)
4. ✅ No ChromaDB references or errors in logs
5. ✅ Embeddings are 768-dimensional (Cohere)
6. ✅ Context is being generated for chunks
7. ✅ Hybrid search returns relevant results
8. ✅ KB operations (create, populate, query, delete) all work

## 📝 Notes

- The backend Supabase instance is separate from any frontend Supabase usage
- Use the SERVICE_ROLE_KEY for backend operations (not the anon key)
- Monitor your API usage for Cohere and Anthropic to avoid rate limits
- Context generation has LRU caching - repeated queries should be faster

---

**Remember to replace `{kb_id}` with your actual KB ID in all commands!** 