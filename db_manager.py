import sqlite3
import json
import time
import os
from typing import List, Dict, Any, Optional
from config import SQLITE_DB_DIR, SQLITE_DB_PATH # Import path from config

# Database path - assuming '/app/' is covered by the persistent disk mount
# If your persistent disk is mounted differently (e.g., only '/app/data/'), adjust this path.
# DB_DIR = "/app/db"  # Store DB in a dedicated subfolder within the persistent area - REMOVED
# DB_PATH = os.path.join(DB_DIR, "kb_metadata.sqlite") - REMOVED

# Ensure the database directory exists
# Use the imported directory path
os.makedirs(SQLITE_DB_DIR, exist_ok=True)

def get_db_connection() -> sqlite3.Connection:
    """Establishes a connection to the SQLite database."""
    # Use the imported DB path
    conn = sqlite3.connect(SQLITE_DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row # Optional: Access columns by name
    return conn

def init_db():
    """Initializes the database and creates the table if it doesn't exist."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS uploaded_jsons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                json_payload TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kb_id ON uploaded_jsons (kb_id);")
        conn.commit()
        print(f"Database initialized successfully at {SQLITE_DB_PATH}")
    except sqlite3.Error as e:
        print(f"Error initializing database: {e}")
        # Depending on severity, you might want to raise the exception
    finally:
        if conn:
            conn.close()

def add_json_payload(kb_id: str, json_data: Dict[str, Any]) -> bool:
    """Adds a JSON payload associated with a kb_id to the database."""
    conn = None
    try:
        json_string = json.dumps(json_data) # Serialize the dict to a JSON string
        current_timestamp = time.time()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO uploaded_jsons (kb_id, timestamp, json_payload)
            VALUES (?, ?, ?)
        """, (kb_id, current_timestamp, json_string))
        conn.commit()
        print(f"Successfully added JSON payload for kb_id: {kb_id}")
        return True
    except sqlite3.Error as e:
        print(f"Error adding JSON payload for kb_id {kb_id}: {e}")
        return False
    except json.JSONDecodeError as json_err:
         print(f"Error serializing JSON data for kb_id {kb_id}: {json_err}")
         return False
    finally:
        if conn:
            conn.close()

def get_json_payloads(kb_id: str) -> List[Dict[str, Any]]:
    """Retrieves all JSON payloads associated with a specific kb_id."""
    conn = None
    payloads = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT json_payload FROM uploaded_jsons WHERE kb_id = ? ORDER BY timestamp ASC", (kb_id,))
        rows = cursor.fetchall()
        
        for row in rows:
            try:
                payload = json.loads(row['json_payload']) # Deserialize JSON string
                payloads.append(payload)
            except json.JSONDecodeError as e:
                print(f"Error decoding stored JSON for kb_id {kb_id}: {e} - Skipping entry.")
                # Optionally log the problematic row content
        
        print(f"Retrieved {len(payloads)} JSON payloads for kb_id: {kb_id}")
        return payloads
    except sqlite3.Error as e:
        print(f"Error retrieving JSON payloads for kb_id {kb_id}: {e}")
        return [] # Return empty list on error
    finally:
        if conn:
            conn.close()

def delete_json_payloads(kb_id: str) -> bool:
    """Deletes all JSON payloads associated with a specific kb_id."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM uploaded_jsons WHERE kb_id = ?", (kb_id,))
        conn.commit()
        # Check if any rows were affected (optional, requires another query or cursor.rowcount check)
        print(f"Successfully deleted JSON payloads for kb_id: {kb_id} (if any existed).")
        return True
    except sqlite3.Error as e:
        print(f"Error deleting JSON payloads for kb_id {kb_id}: {e}")
        return False
    finally:
        if conn:
            conn.close() 