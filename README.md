# Day Three

## Description

Day Three is a contact ladder engine for postnatal newborn follow-up. It runs automated decision logic against keypad replies and free text to identify mothers needing urgent facility care, same-day visits, or human review. Every action is traced to its source: a WHO guideline, an IMNCI rule, or clinical silence. The model drafts messages only; the rule pack decides.

## Spin-up

### Local development

1. **Prepare environment**
   ```bash
   uv venv
   source .venv/bin/activate  # or .venv/Scripts/activate on Windows
   ```

2. **Install dependencies and configure**
   ```bash
   pip install -r requirements.txt
   cp .env.example .env.local
   # Edit .env.local and fill in GEMINI_API_KEY and GCP_PROJECT (if using Firestore)
   ```

3. **Run the app**
   ```bash
   make dev
   ```
   The app will start on `http://localhost:8080` with hot-reload enabled.

4. **Run tests**
   ```bash
   make test
   ```

### Cloud Run deployment

1. **Authenticate with Google Cloud**
   ```bash
   gcloud auth login && gcloud auth application-default login
   ```
   (Required once; the script will prompt if missing)

2. **Deploy to Cloud Run**
   ```bash
   make deploy
   ```
   This command:
   - Enables required GCP APIs (Cloud Run, Cloud Build, Firestore, AI Platform)
   - Creates a Firestore database if needed
   - Deploys the service to Cloud Run (asia-south1, 512Mi, min 0 / max 2 instances)
   - Curls `/api/health` and prints the live `.run.app` URL

3. **Preview the deployment (dry-run)**
   ```bash
   make deploy-dry
   ```
   Prints all gcloud commands that would be executed without running them.

### Deploy status

**Status:** `.run.app` URL will be recorded here after first deployment  
**Last deployed:** (scribe updates after T-05)

## Architecture

See `PLAN.md` for the full design. In brief:

- **Core** (`core/`) is pure Python with no I/O, no network, no clock — tests prove it via AST scan
- **Rules** (`rules/postnatal.v1.json`) are data; every rule action is traced to its source (WHO 2022 PNC, IMNCI, NHM HBNC)
- **Gate** (`core/gate.py`) implements the Danger-Sign Gate; reader can escalate, never dismiss
- **Store** supports both in-memory and Firestore backends (`STORE=memory|firestore`)
- **Model** layer (Gemini via ADK) reads free text and drafts messages; only orchestrator writes
- **Quiet Mode** proves replayability: same decisions with model off (visible in `make quiet-diff`)

## API reference

- `GET /` — User interface
- `GET /api/health` — Service status and model string
- `GET /api/rules` — Full rule pack
- `POST /api/seed` — Initialize a cohort (38 mothers by default)
- `POST /api/advance` — Move time forward, run sweep
- `GET /api/worklist` — Nurse's priority-sorted morning list
- `GET /api/case/{id}` — Mother's timeline with rule citations
- `POST /api/reply` — Record a reply (keypad or free text); gate applies immediately
- `POST /api/replay` — Diff model-on vs model-off decisions for a seed (Quiet Mode proof)
- `POST /api/reset` — Clear a cohort (demo only)

## Testing

Run `make test` to execute the full test suite (target ≥ 95 tests).

Test coverage includes:
- Rule pack schema and citation verification
- Core boundary (no network/clock/env in `core/`)
- Gate logic (precedence, reader cannot clear, merge rules)
- Schedule and routing
- Event log and idempotency
- Store backends (memory and Firestore)
- API routes and clock injection
- Quiet Mode diff (decisions byte-identical, messages differ)

## Environment variables

**Required for Cloud Run:**
- `GEMINI_API_KEY` — Google Generative AI API key
- `GEMINI_MODEL` — Model identifier (default: `gemini-3.5-flash`)
- `GCP_PROJECT` — Google Cloud project ID

**Optional:**
- `STORE` — Storage backend (`memory` or `firestore`; default: `memory`)
- `STORE_PATH` — Path for memory store JSON persistence
- `MODEL_OFF` — Set to `1` to disable the model (Quiet Mode)
- `MODEL_CALL_BUDGET` — Max Gemini calls per sweep (default: `12`)

## Limits & honesty

**What's real:**
- Gemini reader (free text → SymptomForm) via ADK
- Rule pack and its WHO 2022 PNC / IMNCI citations
- Gate logic, schedule, routing, and slot booking
- Cloud Run service and Firestore event log
- Quiet Mode diff (decisions match, only prose changes)

**What's simulated (labelled on-screen):**
- 38 synthetic mothers with seeded, deterministic mix
- The clock (time advances via API, not wall clock)
- Keypad replies (simulated IVR/USSD input)
- SMS/WhatsApp/pager delivery (outbox only, nothing sent)
- Clinic slot table and ASHA assignments
- Free-text reader in Quiet Mode (returns all-`unknown` → `HUMAN_REVIEW`)

**What's not built:**
- Telephony or SMS carrier integration
- Electronic health record (EHR) integration
- Identity, consent, or clinical validation
- The rule pack was transcribed by the builder; `reviewed_by` is `null` unless a clinician reviews it

**The visible limit (rule 8):**
See `docs/adversarial-results.json` for the free-text reader's miss rate on adversarial phrasings. Misses route to `HUMAN_REVIEW` — the pack owns "clear", not the model.
