# 📈 EFFICIENCY IMPROVEMENT PLAN  
Optimising response latency & answer quality for the Multi-Tenant AI Sales Agent backend.

---
## 0. Objectives
1. **Lower average first-token latency** for common queries to < 300 ms.  
2. **Reduce computational cost** (LLM & DB round-trips) by ≥ 50 %.  
3. **Maintain or improve answer accuracy** & human-likeness.  
4. **Keep codebase maintainable & test-covered.**

---
## 1. Roadmap at a Glance
| ‑ | Initiative | Effort | ETA | Impact |
|---|------------|--------|-----|--------|
|QW-1|Small-talk fast-path|½ day|Day 1|🚀 Latency ↓90 % for greetings|
|QW-2|Trim history to N turns|½ day|Day 1|RAM ↓; Supabase IO ↓|
|QW-3|Executor caching|1 day|Day 2|CPU ↓; latency ↓100-200 ms|
|QW-4|Streaming answers|1 day|Day 3|Perceived latency ↓80 %|
|OPT-1|Embedding & search cache|0.5 day|Day 4|Embeddings API ↓70 %|
|OPT-2|Cohere *rerank*|1 day|Day 4|Answer relevance ↑|
|OPT-3|Hallucination guard|1 day|Day 5|Trust ↑, errors ↓|
|OBS|Metrics + Grafana|0.5 day|Day 5|Visibility ↑|
|BG|Nightly KB auto-update|2 days|Sprint 2|Hand-offs ↓25 %|
|FAQ|Lightweight FAQ layer|2 days|Sprint 2|Sub-200 ms answers|

> **Legend**  
> • *QW* = Quick-Win (hours)  • *OPT* = Optimisation  • *OBS* = Observability  • *BG* = Background job  • *FAQ* = Optional epic

---
## 2. Detailed Tasks
### QW-1 — Small-Talk Fast-Path
1. Add `utils/small_talk.py` with heuristic matcher (`rapidfuzz`).  
2. In `chat_endpoint()` **before** memory load:  
   ```python
   if looks_like_small_talk(msg):
       save_history(role="ai", content=TEMPLATED_REPLY)
       return ChatResponse(content=TEMPLATED_REPLY, type="answer")
   ```
3. Unit-test (`tests/test_small_talk.py`).

### QW-2 — History Window
* Signature change in `supabase_metadata_manager.get_conversation_history(limit:int=12)`.
* Update callers (`chat.py`, `agent_manager.py`).

### QW-3 — Agent Executor Cache
* Introduce `_AGENT_CACHE` in `agent_manager.py`.  
* Keyed by `kb_id`; attach new conversation-specific memory on each call.  
* Invalidate on KB config change.

### QW-4 — Streaming Responses
* Switch `/agents/{kb_id}/chat` HTTP to `StreamingResponse`.  
* Use `AsyncIteratorCallbackHandler` to yield tokens.  
* Update front-end widget (not in scope here) to consume SSE/WebSocket stream.

### OPT-1 — Embedding & Hybrid-Search Cache
* Redis key pattern:  
  *Embeddings*: `emb:{sha256(query)}` → `bytes`  
  *Doc search*: `search:{kb}:{sha256(query)}` → `json` (list ids).
* TTL = 1 h.

### OPT-2 — Cohere Rerank
* After `hybrid_search` → top-20 docs → call `cohere.rerank`.  
* Store `rerank_score` for analytics.

### OPT-3 — Hallucination Guard
* Post-processing chain asks LLM to self-verify facts.  
* On "No", replace answer with fallback apology.

### OBS — Prometheus Metrics
* Add `prometheus_fastapi_instrumentator` middleware.  
* Custom counters: `chat_latency_ms`, `agent_calls_total`, `handoff_rate`.

### BG — Nightly KB Updater
* New script `scripts/nightly_kb_update.py` triggered via cron / GitHub Actions.  
* Pull unanswered questions → auto-scrape / search docs → propose answers → human review queue.

### FAQ — In-Memory FAQ Model (Optional)
* Fine-tune `all-MiniLM-L6-v2` on company FAQs.  
* Serve via `faiss` in-process; threshold 0.9.

---
## 3. Delivery Phases
1. **Sprint 0 (today)**   Quick-wins QW-1 & QW-2 (latency relief).  
2. **Sprint 1 (1-2 days)** QW-3, QW-4 + OPT-1 (cost + perceived speed).  
3. **Sprint 2 (3-5 days)** OPT-2, OPT-3, OBS, BG job.  
4. **Sprint 3 (optional)** FAQ layer & user-feedback tuning.

---
## 4. Testing & Roll-back
* **Unit Tests** for new utils, cache behaviour, streaming handler.  
* **Load-test** before / after with Locust – target 50 RPS.  
* Can roll-back by toggling `FAST_PATH_ENABLED` env flag.

---
## 5. Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|-----------|
| Streaming incompatibility with some clients | Stuck spinners | Feature-flag per client version |
| Cache staleness after KB update | Outdated answers | Invalidate cache on `kb_update_log` trigger |
| Rapidfuzz false-positives | Over-simple answers | Keep list small; add analytics counter |
| Increased code complexity | Maintenance cost | Separate modules + full test coverage |

---
## 6. Ownership
| Area | Owner |
|------|-------|
| Fast-path & cache | Backend team A |
| Streaming & front-end | FE + BE joint |
| Rerank / Guardrails | ML-Ops |
| Metrics & Grafana | Dev-Ops |
| Background updater | Content Ops |

---
*Document generated 2025-06-12.* 