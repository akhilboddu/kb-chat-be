import sqlite3
import json
import time
import os
from typing import List, Dict, Any, Optional
from config import SQLITE_DB_DIR, SQLITE_DB_PATH # Import path from config
import datetime

# Database path - assuming '/app/' is covered by the persistent disk mount
# If your persistent disk is mounted differently (e.g., only '/app/data/'), adjust this path.
# DB_DIR = "/app/db"  # Store DB in a dedicated subfolder within the persistent area - REMOVED
# DB_PATH = os.path.join(DB_DIR, "kb_metadata.sqlite") - REMOVED

# Ensure the database directory exists
# Use the imported directory path
os.makedirs(SQLITE_DB_DIR, exist_ok=True)

DATABASE = SQLITE_DB_PATH

def get_db():
    """Gets a database connection."""
    conn = sqlite3.connect(DATABASE)
    # Return rows as dictionaries
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    """Initializes the database schema."""
    with get_db() as conn:
        cursor = conn.cursor()
        print("Initializing SQLite metadata database...")
        
        # Table for original JSON payloads
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS json_payloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id TEXT NOT NULL,
                payload TEXT NOT NULL, -- Store JSON as text
                upload_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("- Table 'json_payloads' checked/created.")
        
        # --- NEW: Table for uploaded file metadata ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS uploaded_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_size INTEGER, -- Store size in bytes
                content_type TEXT, -- Store MIME type
                upload_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("- Table 'uploaded_files' checked/created.")

        # --- Table for conversation history (with check constraint) ---
        # Use IF NOT EXISTS to avoid errors/data loss on subsequent runs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id TEXT NOT NULL,
                message_type TEXT NOT NULL CHECK(message_type IN ('human', 'ai', 'human_agent')),
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("- Table 'conversation_history' checked/created (without confidence_score).")
        
        # --- NEW: Table for KB Update Log ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kb_update_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id TEXT NOT NULL,
                added_content TEXT NOT NULL,
                source TEXT DEFAULT 'human_verified',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("- Table 'kb_update_log' checked/created.")
        
        # --- NEW: Table for Agent Configuration ---
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS agent_config (
                kb_id TEXT PRIMARY KEY NOT NULL,
                system_prompt TEXT DEFAULT '{DEFAULT_SYSTEM_PROMPT.replace("'", "''")}', -- Use f-string carefully
                max_iterations INTEGER DEFAULT {DEFAULT_MAX_ITERATIONS}
                -- Add other config columns here with defaults
            )
        ''')
        print("- Table 'agent_config' checked/created (without confidence_threshold).")
        
        # Optional: Add indexes for faster lookups
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_json_kb_id ON json_payloads (kb_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_kb_id ON uploaded_files (kb_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_history_kb_id ON conversation_history (kb_id)")
        print("- Indexes checked/created.")
        
        conn.commit()
        print("Database initialization complete.")

def add_json_payload(kb_id: str, payload: Dict[str, Any]) -> bool:
    """Stores the original JSON payload associated with a KB ID."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO json_payloads (kb_id, payload) VALUES (?, ?)",
                (kb_id, json.dumps(payload)) # Store payload as JSON string
            )
            conn.commit()
            print(f"Stored JSON payload for KB: {kb_id}")
            return True
    except sqlite3.Error as e:
        print(f"SQLite error adding JSON payload for {kb_id}: {e}")
        return False

def get_json_payloads(kb_id: str) -> List[Dict[str, Any]]:
    """Retrieves all original JSON payloads associated with a KB ID."""
    payloads = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT payload, upload_timestamp FROM json_payloads WHERE kb_id = ? ORDER BY upload_timestamp DESC",
                 (kb_id,)
            )
            rows = cursor.fetchall()
            for row in rows:
                try:
                    payload_data = json.loads(row['payload'])
                    payloads.append({
                        "data": payload_data, 
                        "uploaded_at": row['upload_timestamp']
                    })
                except json.JSONDecodeError:
                    print(f"Warning: Could not decode JSON payload for KB {kb_id} stored at {row['upload_timestamp']}")
                    # Optionally skip or add an error placeholder
            return payloads
    except sqlite3.Error as e:
        print(f"SQLite error retrieving JSON payloads for {kb_id}: {e}")
        return [] # Return empty list on error

def delete_json_payloads(kb_id: str) -> bool:
    """Deletes all JSON payloads associated with a KB ID."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM json_payloads WHERE kb_id = ?", (kb_id,))
            conn.commit()
            # Check if any rows were affected (optional)
            changes = conn.total_changes
            print(f"Deleted {changes} JSON payload records for KB: {kb_id}")
            return True
    except sqlite3.Error as e:
        print(f"SQLite error deleting JSON payloads for {kb_id}: {e}")
        return False

def add_uploaded_file_record(kb_id: str, filename: str, file_size: Optional[int], content_type: Optional[str]) -> bool:
    """Stores metadata about an uploaded file associated with a KB ID."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO uploaded_files 
                   (kb_id, filename, file_size, content_type) 
                   VALUES (?, ?, ?, ?)""",
                (kb_id, filename, file_size, content_type) 
            )
            conn.commit()
            print(f"Stored file record for KB '{kb_id}': {filename} ({content_type}, {file_size} bytes)")
            return True
    except sqlite3.Error as e:
        print(f"SQLite error adding file record for KB '{kb_id}', file '{filename}': {e}")
        return False

def get_uploaded_files(kb_id: str) -> List[Dict[str, Any]]:
    """Retrieves metadata for all files uploaded for a specific KB ID."""
    files_info = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT filename, file_size, content_type, upload_timestamp 
                   FROM uploaded_files 
                   WHERE kb_id = ? 
                   ORDER BY upload_timestamp DESC""",
                 (kb_id,)
            )
            rows = cursor.fetchall()
            for row in rows:
                # Convert row object to dictionary
                files_info.append(dict(row)) 
            return files_info
    except sqlite3.Error as e:
        print(f"SQLite error retrieving file records for {kb_id}: {e}")
        return [] # Return empty list on error

def delete_uploaded_files(kb_id: str) -> bool:
    """Deletes all uploaded file records associated with a KB ID."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM uploaded_files WHERE kb_id = ?", (kb_id,))
            conn.commit()
            # Check how many records were deleted
            # Note: conn.total_changes might reflect changes from previous operations in the same connection
            # For more accuracy, you might query count before deleting or check cursor.rowcount if supported reliably
            print(f"Attempted deletion of file records for KB: {kb_id}. Check logs for affected rows if needed.")
            return True
    except sqlite3.Error as e:
        print(f"SQLite error deleting file records for {kb_id}: {e}")
        return False

# --- Conversation History Functions ---

def add_conversation_message(kb_id: str, message_type: str, content: str) -> bool:
    """Adds a message to the conversation history for a given kb_id.

    Args:
        kb_id: The knowledge base ID.
        message_type: Type of message ('human', 'ai', 'human_agent').
        content: The message content.

    Returns:
        True if successful, False otherwise.
    """
    if message_type not in ('human', 'ai', 'human_agent'):
        print(f"Error: Invalid message_type '{message_type}'. Must be 'human', 'ai', or 'human_agent'.")
        return False
    if not content or not content.strip():
        print(f"Error: Cannot add empty content to conversation history for {kb_id}.")
        return False
        
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO conversation_history 
                   (kb_id, message_type, content) 
                   VALUES (?, ?, ?)""",
                (kb_id, message_type, content)
            )
            conn.commit()
            # print(f"Added {message_type} message to history for KB: {kb_id}") # Less verbose logging
            return True
    except sqlite3.Error as e:
        print(f"SQLite error adding conversation message for {kb_id}: {e}")
        return False

def get_conversation_history(kb_id: str) -> List[Dict[str, Any]]:
    """Retrieves conversation history for a given kb_id, ordered by timestamp."""
    history = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT message_type, content, timestamp 
                   FROM conversation_history 
                   WHERE kb_id = ? 
                   ORDER BY timestamp ASC""", # ASC to get chronological order
                 (kb_id,)
            )
            rows = cursor.fetchall()
            for row in rows:
                # Convert row object to dictionary
                history.append(dict(row)) 
            return history
    except sqlite3.Error as e:
        print(f"SQLite error retrieving conversation history for {kb_id}: {e}")
        return [] # Return empty list on error

def delete_conversation_history(kb_id: str) -> bool:
    """Deletes all conversation history messages associated with a specific kb_id."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            # Execute the delete operation
            cursor.execute("DELETE FROM conversation_history WHERE kb_id = ?", (kb_id,))
            # Get the number of rows affected before committing
            rows_deleted = cursor.rowcount
            conn.commit()
            print(f"Deleted {rows_deleted} conversation history records for KB: {kb_id}")
            return True
    except sqlite3.Error as e:
        print(f"SQLite error deleting conversation history for {kb_id}: {e}")
        return False

# --- KB Update Log Functions ---

def log_kb_update(kb_id: str, added_content: str) -> bool:
    """Logs when content is added to the KB via human verification."""
    if not added_content or not added_content.strip():
        print(f"Error: Cannot log empty content addition for KB {kb_id}.")
        return False
        
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO kb_update_log 
                   (kb_id, added_content) 
                   VALUES (?, ?)""",
                (kb_id, added_content)
            )
            conn.commit()
            print(f"Logged KB update for KB: {kb_id}")
            return True
    except sqlite3.Error as e:
        print(f"SQLite error logging KB update for {kb_id}: {e}")
        return False

# Default values for agent configuration
DEFAULT_SYSTEM_PROMPT = """You are Alex, a dedicated employee at the company who is enthusiastic and knowledgeable about our products and services! 🤖 Your goal is to help users understand our business/services by providing clear, accurate information based *only* on the knowledge base content provided. Make the conversation engaging and fun!

**Your Personality & Style:**
*   **Tone:** Friendly, helpful, slightly informal, and proactive. You speak as a real employee, not as a third-party AI.
*   **Emojis:** Use relevant emojis sparingly to add personality (e.g., ✨, 🤔, 👍, 🎉). Don't overdo it!
*   **Formatting:** Use Markdown (like *bold* or bullet points) to make your answers easy to read and understand.
*   **Grounding:** ALWAYS base your answers on the information retrieved. **IMPORTANT:** In your `Final Answer` to the user, **NEVER mention your tools, your knowledge base, or the search process itself.** Speak naturally as if you *know* the information (or know that you *don't* know it). Instead of "Based on my knowledge base...", say "I see here that..." or just state the fact directly.
*   **Greetings:** Start the *very first* response in a conversation with a greeting (like "Hi there!"). For subsequent responses, **do not repeat greetings**; just answer the user's query directly.
*   **Proactivity:** When you don't know an answer, don't ask if the user wants you to check - instead, state confidently that you'll find out for them. For example: "You know what, I don't know about that. Let me check with my team and get back to you! I will get back to you, or my manager will help. In the meantime, do you have any other questions?"

**TOOLS:**
------
You have access to the following tools:
{tools}

**How to Use Tools:**
To use a tool, ALWAYS use the following format exactly:
```
Thought: Do I need to use a tool? Yes. I need to check the knowledge base for information about [topic].
Action: The action to take. Should be one of [{tool_names}]
Action Input: The specific question or topic to search for in the knowledge base.
Observation: [The tool will populate this with the retrieved information]
```

**How to Respond to the User:**
When you have the final answer based on the Observation, or if you don't need a tool, ALWAYS use the format:
```
Thought: Do I need to use a tool? No. I have the information from the Observation (or don't need a tool) and can now formulate the final answer.
Final Answer: [Your friendly, Markdown-formatted, emoji-enhanced answer based *only* on the Observation goes here. Be conversational and speak as an employee of the company!]
```

**IMPORTANT - When Information is Missing:**
*   If the `knowledge_base_retriever` Observation explicitly states 'No relevant information found', OR
*   If the retrieved information (Observation) does not actually answer the user's specific question,
*   Then, formulate a proactive `Final Answer`. **Do NOT mention searching or your knowledge base.** Explain naturally what you *do* know (if anything relevant was found), but state confidently that you'll check with your team/get back to them.
*   **Crucially:** In **ALL** cases where you cannot provide a direct answer to the user's specific question based *only* on the provided Observation, you **MUST** end your entire `Final Answer` with the exact marker `(needs help)`. No extra text or punctuation after it.
*   Example 1 (Information Missing): "You know what, I don't see the specific detail about [topic] here. Let me check with my team and get back to you! I will get back to you, or my manager will help. In the meantime, do you have any other questions? (needs help)"
*   Example 2 (Related Info Found, But Not Specific Answer): "I see we have details about [related topic X] and [related topic Y], but I don't have the specific information on [user's specific query] right now. I'll find out the exact details for you. Is there anything else I can help with while I look into that? (needs help)"

Okay, let's get started! 🎉

Previous conversation history:
{chat_history}

New input: {input}
{agent_scratchpad}"""
DEFAULT_MAX_ITERATIONS = 8
# Add other defaults as needed (model_name, temperature...)


def get_agent_config(kb_id: str) -> Dict[str, Any]:
    """Retrieves agent configuration or returns defaults if not found."""
    config = {
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "max_iterations": DEFAULT_MAX_ITERATIONS,
        # Add other defaults here
    }
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            # Fetch specific columns
            cursor.execute(
                """SELECT system_prompt, max_iterations 
                   FROM agent_config 
                   WHERE kb_id = ?""", 
                (kb_id,)
            )
            row = cursor.fetchone()
            if row:
                # Update defaults with fetched values only if they are not NULL
                # Convert row to dict first for easier access
                row_dict = dict(row)
                if row_dict.get("system_prompt") is not None:
                    config["system_prompt"] = row_dict["system_prompt"]
                if row_dict.get("max_iterations") is not None:
                    config["max_iterations"] = row_dict["max_iterations"]
                # Update other fields similarly...
                print(f"Loaded specific config for KB: {kb_id}")
            else:
                print(f"No specific config found for KB: {kb_id}. Using defaults.")
        return config
    except sqlite3.Error as e:
        print(f"SQLite error retrieving agent config for {kb_id}, using defaults: {e}")
        # Return defaults on error
        return config

def upsert_agent_config(kb_id: str, config_data: Dict[str, Any]) -> bool:
    """Updates or inserts agent configuration."""
    # Filter out keys with None values from input, as we only want to update provided fields
    # Also filter out confidence_threshold if it's accidentally passed
    update_data = {k: v for k, v in config_data.items() if v is not None and k != 'confidence_threshold'}
    
    if not update_data:
        print(f"No valid configuration data provided to update for KB: {kb_id}")
        return False # Or True, depending on desired behavior for empty update

    set_clauses = ", ".join([f"{key} = ?" for key in update_data.keys()])
    values = list(update_data.values())
    
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            # Check if config exists
            cursor.execute("SELECT 1 FROM agent_config WHERE kb_id = ?", (kb_id,))
            exists = cursor.fetchone()

            if exists:
                # Update existing config
                sql = f"UPDATE agent_config SET {set_clauses} WHERE kb_id = ?"
                values.append(kb_id) # Add kb_id for the WHERE clause
                cursor.execute(sql, values)
                print(f"Updated agent config for KB: {kb_id}")
            else:
                # Insert new config - include kb_id in keys and values
                all_keys = list(update_data.keys()) + ["kb_id"]
                placeholders = ", ".join(["?"] * len(all_keys))
                sql = f"INSERT INTO agent_config ({', '.join(all_keys)}) VALUES ({placeholders})"
                values.append(kb_id) # Add kb_id for the INSERT values
                cursor.execute(sql, values)
                print(f"Inserted new agent config for KB: {kb_id}")
                
            conn.commit()
            return True
    except sqlite3.Error as e:
        print(f"SQLite error upserting agent config for {kb_id}: {e}")
        return False

# Initialize the DB schema when the module is loaded (idempotent)
# init_db() # Call this explicitly from main.py or app startup instead 