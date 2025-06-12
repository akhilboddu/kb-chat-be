# SQLite ➜ Supabase Migration Guide  
**File:** `SQLLITE_REPLACEMNT.md`  
**Goal:** Remove every SQLite dependency from the KB-Chat backend and move *all* metadata / operational tables to Supabase (PostgreSQL), achieving a single-database architecture that is easier to scale, back-up and secure.

---
## ⏩ Executive Summary
1. **Why migrate?**  
   • Eliminate dual-DB complexity  
   • One source of truth, RLS, real-time listeners  
   • No file-based state → container friendly  
2. **What moves?**  
   `uploaded_files`, `json_payloads`, `conversation_history`, `scraping_status`, `agent_config`, `kb_update_log` tables.  
3. **Impact:** No public API or response changes; only internal storage layer and imports.

---
## 1. Supabase Schema Add-On
Run **once** (e.g. with Supabase SQL editor or migration CLI):
```sql
-- 1.1  File uploads
CREATE TABLE IF NOT EXISTS uploaded_files (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kb_id            TEXT REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
  filename         TEXT NOT NULL,
  file_size        INTEGER,
  content_type     TEXT,
  upload_timestamp TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_kb ON uploaded_files(kb_id);

-- 1.2  JSON payload archive
CREATE TABLE IF NOT EXISTS json_payloads (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kb_id            TEXT REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
  payload          JSONB NOT NULL,
  upload_timestamp TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_json_payloads_kb ON json_payloads(kb_id);

-- 1.3  Conversation history
CREATE TABLE IF NOT EXISTS conversation_history (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kb_id      TEXT REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
  message_type TEXT CHECK (message_type IN ('human','ai','human_agent')),
  content     TEXT NOT NULL,
  ts          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conv_hist_kb ON conversation_history(kb_id);

-- 1.4  Scraping status tracker
CREATE TABLE IF NOT EXISTS scraping_status (
  kb_id         TEXT PRIMARY KEY REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
  status        TEXT CHECK (status IN ('processing','completed','failed')),
  submitted_url TEXT NOT NULL,
  pages_scraped INTEGER DEFAULT 0,
  total_pages   INTEGER,
  error         TEXT,
  last_update   TIMESTAMPTZ DEFAULT now(),
  progress_data JSONB
);

-- 1.5  Per-agent configuration
CREATE TABLE IF NOT EXISTS agent_config (
  kb_id          TEXT PRIMARY KEY REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
  system_prompt  TEXT,
  max_iterations INTEGER DEFAULT 10,
  updated_at     TIMESTAMPTZ DEFAULT now()
);

-- 1.6  KB update audit log
CREATE TABLE IF NOT EXISTS kb_update_log (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kb_id         TEXT REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
  added_content TEXT NOT NULL,
  source        TEXT DEFAULT 'human_verified',
  ts            TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kb_update_kb ON kb_update_log(kb_id);
```
*Add RLS policies* if your project uses tenant isolation via JWT claims.

---
## 2. New Python Module – `supabase_metadata_manager.py`
A **drop-in replacement** that re-implements every function from `db_manager.py` using the Supabase client.
```python
# app/core/supabase_metadata_manager.py
from app.core.supabase_client import supabase

# === FILE UPLOADS ===

def add_uploaded_file_record(kb_id, filename, file_size, content_type):
    supabase.table('uploaded_files').insert({
        'kb_id': kb_id, 'filename': filename,
        'file_size': file_size, 'content_type': content_type
    }).execute()
    return True

def get_uploaded_files(kb_id):
    res = supabase.table('uploaded_files').select('*').eq('kb_id', kb_id).order('upload_timestamp', desc=True).execute()
    return res.data  # list[dict]
```
*Repeat the same pattern for every method* (`add_json_payload`, `update_scrape_status`, `get_agent_config`, etc.).

### Helper: LRU cache for read-heavy endpoints
```python
from functools import lru_cache

@lru_cache(maxsize=2048)
def get_agent_config_cached(kb_id):
    return get_agent_config(kb_id)
```
Cache invalidation occurs in `upsert_agent_config`.

---
## 3. Global Import Swap
1. **`app/core/__init__.py`**
```diff
-from app.core.db_manager import *
+from app.core.supabase_metadata_manager import *
```
2. Remove `init_db()` call from `app/main.py` – no SQLite bootstrap needed.

---
## 4. Data Migration Script
File: `scripts/migrate_sqlite_to_supabase.py`
```python
import sqlite3, json
from app.core.supabase_client import supabase
SQLITE_PATH = './db/kb_metadata.sqlite'
conn = sqlite3.connect(SQLITE_PATH)
conn.row_factory = sqlite3.Row

TABLES = [
    'uploaded_files', 'json_payloads', 'conversation_history',
    'scraping_status', 'agent_config', 'kb_update_log'
]
for tbl in TABLES:
    rows = conn.execute(f'SELECT * FROM {tbl}').fetchall()
    if not rows:
        print(f'Skip {tbl} – empty')
        continue
    supabase.table(tbl).insert([dict(r) for r in rows]).execute()
    print(f'Migrated {len(rows)} rows → {tbl}')
print('✅ Migration finished')
```
Run once after creating the new tables.

---
## 5. Dependency & File Clean-up
- Remove `app/core/db_manager.py` and references.
- Delete `./db` folder and `SQLITE_DB_*` vars from `.env` and `core/config.py`.
- **requirements.txt**: remove `aiosqlite`.
- Update **Dockerfile / docker-compose**: no volume mount for `./db`.

---
## 6. Testing Checklist
| Area | Test | Expected |
|------|------|----------|
| File uploads | `POST /agents/{kb}/upload` + `GET /agents/{kb}/files` | Records appear in Supabase `uploaded_files` |
| JSON ingest | `POST /agents/{kb}/json` + `GET /agents/{kb}/json` | Payloads stored & retrievable |
| Chat history | Chat via `/chat` endpoints, then `GET /agents/{kb}/history` | All messages present |
| Scraper | Start scrape → poll `/scrape-status` | Status updates correctly |
| Config | `GET /agents/{kb}/config` & `PUT` | Config persists in `agent_config` |
| Update log | Add verified knowledge → check `kb_update_log` | Audit row exists |

Automate with `pytest -k supabase_metadata`.

---
## 7. Deployment & Rollback
1. Apply SQL migration in production.  
2. Run `migrate_sqlite_to_supabase.py` once; verify row counts.  
3. Deploy code with new module and removed SQLite.  
4. Monitor logs; if needed, rollback by redeploying previous container and keeping the original SQLite file.

---
## 8. Timeline & Effort
| Task | Owner | Est. hrs |
|------|-------|----------|
| Supabase table creation & RLS | Backend | 1 |
| Python module (`supabase_metadata_manager`) | Backend | 3 |
| Import swap & removal of SQLite code | Backend | 1 |
| Migration script + dry-run | Backend | 2 |
| QA & automated tests | QA | 3 |
| Documentation update | Docs | 0.5 |
| **Total** |  | **10.5 hrs** |

---
## 9. Post-Migration Benefits
* 🔄 Real-time subscriptions (possible future feature)
* 🔒 Unified RLS enforcement across *all* agent data
* 📦 One backup strategy – managed by Supabase
* ☁️ Stateless containers – easier horizontal scaling
* 🧩 Cleaner code-base – no local DB initialization, fewer deps

---
**Migration Status:** *Planned – awaiting approval*  
When approved, create Supabase migration SQL + PR with the new module and deletion of `db_manager.py`. 