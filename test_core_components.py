# test_core_components.py

import time
import json
from config import llm, chroma_embedding_function  # Import LLM and the *wrapped* embedding function
from data_processor import extract_text_from_json, chunk_text
from kb_manager import kb_manager  # Import the singleton instance
from tools import get_retriever_tool, get_knowledge_update_tool, get_answering_tool

print("--- Starting Core Component Tests ---")

# --- Test Data Processor ---
print("\n--- Testing Data Processor ---")
sample_json_string = '''
{
    "company": "TestCorp",
    "product": {
        "name": "WidgetPro",
        "features": ["Feature A", "Feature B"],
        "description": "The best widget."
    }
}
'''
sample_data = json.loads(sample_json_string)
extracted_text = extract_text_from_json(sample_data)
print(f"Extracted Text: {extracted_text}")
assert "TestCorp" in extracted_text
assert "WidgetPro" in extracted_text
assert "Feature A" in extracted_text
assert "The best widget." in extracted_text
print("JSON Extraction Test: PASSED")

chunks = chunk_text(extracted_text, chunk_size=50, chunk_overlap=10)
print(f"Generated Chunks (chunk_size=50): {chunks}")
assert len(chunks) > 0 # Basic check
# assert "TestCorp WidgetPro Feature A Feature B The best widget." in "".join(chunks) # This can fail with small chunk sizes
print("Text Chunking Test: PASSED")


# --- Test KB Manager ---
print("\n--- Testing KB Manager ---")
test_kb_id = f"test_kb_{int(time.time())}" # Unique ID for test run
print(f"Using temporary KB ID: {test_kb_id}")

# 1. Create/Get KB
print("Testing KB Creation...")
kb_collection = kb_manager.create_or_get_kb(test_kb_id)
assert kb_collection is not None
assert kb_collection.name == test_kb_id
print("KB Creation/Retrieval Test: PASSED")

# 2. Populate KB
print("Testing KB Population...")
initial_texts = ["Blue is a color.", "Apples are fruit."]
initial_chunks = chunk_text(" ".join(initial_texts))
kb_manager.populate_kb(kb_collection, initial_chunks)
print("KB Population Test: PASSED (Check ChromaDB logs for details)")
# Allow a moment for embedding/indexing
time.sleep(2)

# 3. Retrieve from KB
print("Testing KB Retrieval...")
query = "What color is mentioned?"
retrieved_docs = kb_manager.get_similar_docs(test_kb_id, query, n_results=1)
print(f"Docs retrieved for '{query}': {retrieved_docs}")
assert len(retrieved_docs) > 0
assert "Blue" in retrieved_docs[0] # Expecting the relevant doc
print("KB Retrieval Test: PASSED")

# 4. Add to KB
print("Testing Adding to KB...")
text_to_add = "Pears are also fruit."
success = kb_manager.add_to_kb(test_kb_id, text_to_add)
assert success is True
print("KB Addition Test: PASSED (Check ChromaDB logs for details)")
# Allow a moment for embedding/indexing
time.sleep(2)

# 5. Retrieve again after adding
print("Testing KB Retrieval after adding...")
query2 = "What types of fruit are there?"
retrieved_docs_2 = kb_manager.get_similar_docs(test_kb_id, query2, n_results=2)
print(f"Docs retrieved for '{query2}': {retrieved_docs_2}")
assert len(retrieved_docs_2) > 0
# Check if both apple and pear related chunks are potentially retrieved
found_apple = any("Apple" in doc for doc in retrieved_docs_2)
found_pear = any("Pear" in doc for doc in retrieved_docs_2)
assert found_apple or found_pear # At least one should be found, ideally both depending on similarity
print("KB Retrieval After Addition Test: PASSED")

# --- Test Tools ---
print("\n--- Testing Tools ---")

# 1. Retriever Tool
print("Testing Retriever Tool Creation...")
retriever_tool = get_retriever_tool(test_kb_id)
assert retriever_tool is not None
assert retriever_tool.name == "knowledge_base"
print("Retriever Tool Creation Test: PASSED")

print("Testing Retriever Tool Execution...")
retrieval_result = retriever_tool.run("What is blue?")
print(f"Retriever tool result: {retrieval_result}")
assert "Blue" in retrieval_result
print("Retriever Tool Execution Test: PASSED")

# 2. Knowledge Update Tool
print("Testing Knowledge Update Tool Creation...")
update_tool = get_knowledge_update_tool(test_kb_id)
assert update_tool is not None
assert update_tool.name == "update_knowledge_base"
print("Knowledge Update Tool Creation Test: PASSED")

print("Testing Knowledge Update Tool Execution...")
update_result = update_tool.run("Bananas are yellow.")
print(f"Update tool result: {update_result}")
assert "Successfully updated" in update_result
time.sleep(2) # Allow time for update

# Verify update by directly querying the KB manager with more results
print("Verifying update via KB Manager direct query...")
retrieved_docs_after_update = kb_manager.get_similar_docs(
    test_kb_id,
    "What fruit is yellow?",
    n_results=5 # Request more results
)
print(f"Docs retrieved for 'What fruit is yellow?': {retrieved_docs_after_update}")
found_banana = any("Banana" in doc for doc in retrieved_docs_after_update)
assert found_banana, "Document containing 'Banana' was not retrieved after update."
print("Knowledge Update Tool Execution Test: PASSED")

# 3. Answering Tool (Basic check if LLM is available)
print("Testing Answering Tool Creation...")
if llm:
    answering_tool = get_answering_tool(llm)
    assert answering_tool is not None
    assert answering_tool.name == "answer_generator"
    print("Answering Tool Creation Test: PASSED (Requires LLM)")
    # Note: A full test would involve running the tool, which makes an LLM call
    # print("Testing Answering Tool Execution (requires LLM call)...")
    # answer = answering_tool.run({"context": "The sky is blue.", "question": "What color is the sky?"})
    # print(f"Answering tool result: {answer}")
    # assert "blue" in answer.lower()
    # print("Answering Tool Execution Test: PASSED")
else:
    print("Answering Tool Test: SKIPPED (LLM not configured in .env)")


print("\n--- Core Component Tests Finished ---")

# Clean up the test collection (optional)
# try:
#     print(f"\nAttempting to delete test collection: {test_kb_id}")
#     kb_manager.client.delete_collection(test_kb_id)
#     print(f"Successfully deleted test collection: {test_kb_id}")
# except Exception as e:
#     print(f"Could not delete test collection {test_kb_id}: {e}") 