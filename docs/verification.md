# Verification record

## Automated verification

48 tests pass with Python 3.12 on Windows. The suite includes:

- Gemini structured-response contracts, API-key redaction, embedding dimensions and cache isolation.
- Real local FAISS indexing/search with mocked Gemini embeddings.
- End-to-end mocked Gemini incident workflow, source verification and restricted function-call planning.
- Unsupported/missing verifier claims block actionable proposals.
- Human approval, exact payload digest, stale evidence, expiration, rejection, concurrency and idempotency.
- Fresh-database initialization through the CLI, document ingestion revisions and MCP stdio tool listing.
- SSE delivers final claims after verification.

Ruff checks and JavaScript syntax checks pass. Docker Compose configuration parses. The offline synthetic evaluation passes; its tiny fixture metrics are not a general accuracy claim.

## Requirements update validation

- Parent-child containment across a 2,000-word document.
- Metadata and document-role filters, direct-source access and saved-evidence revocation.
- Owned conversation history and follow-ups that re-read current permissions.
- Five parameterized prompt-injection query/document cases.
- Text-first PDF extraction, sparse-page OCR routing and rejection of empty OCR output (mocked PDF pages/OCR engine).
- Persistent SSE operation/stage telemetry, failed-stream metrics, estimated known/unknown costs and operator-only access.
- Previously approved ticket visibility and receipt access after document access is revoked.

The expanded offline evaluation has four workflow cases and seven retrieval cases. Workflow accuracy and hit rate@3 are 1.0, MRR@3 is 0.905, and nDCG@3 is 0.929. The JSON report in `reports/evaluation.json` contains configuration, thresholds, dataset/corpus hashes, per-case labels/results and citation coverage. These are synthetic regression results, not a held-out benchmark.

No new live Gemini requests were made for this requirements update. Tests use mocked provider responses. The live checks below describe the earlier setup session.

## Earlier live provider checks

The user's key is stored only in ignored `.env` and is never returned to the browser. A check found no copy of that key in application source, tests, documentation, `.env.example`, or Compose configuration.

- Google's model listing accepted the key.
- `gemini-2.5-flash` returned HTTP 404 with an explicit message that it is unavailable to new users and recommended `gemini-3.8-flash`.
- Configuration was updated to `gemini-3.8-flash`.
- `gemini-embedding-001` successfully returned a 768-dimensional embedding.
- Structured generation with the recommended model and a listed stable Flash-Lite alternative returned HTTP 503 after bounded retries.
- A minimal plain-text generation request also returned HTTP 503, explicitly reporting high demand and asking to retry later. The failure is not limited to the structured-output request.

Successful live answer generation and a full live Gemini incident run are not claimed. Use `python -m copilot.cli doctor --live` to recheck availability before recording. The app displays API failures instead of presenting offline results as Gemini output.

## Not yet validated

- Full live Gemini generation, claim checking and function planning, pending provider availability.
- PostgreSQL/OpenSearch container execution; Docker is optional for the requested local setup.
- Scanned-PDF OCR with a locally installed Tesseract executable.
- Production multi-user deployment, SSO, real customer records or external ticket delivery.

The `requirements.lock` file records installed core/test dependencies as pip constraints. The optional legacy retrieval and OCR extras are not fully locked by that snapshot.

## Browser check

The UI was exercised on a separate temporary SQLite database with explicit local/extractive settings: login, streamed investigation, contextual follow-up, and the Monitoring table all worked. This check made no Gemini calls and did not modify the user's normal ticket ledger.

## Public release validation (7 November 2026)

The dark interface was checked on desktop and at 390 x 844 using an isolated local/extractive database. Browser checks covered login, streamed investigation, two-ticket approval, contextual follow-up, rejection, cited knowledge answers, audit entries and monitoring. Ruff, JavaScript syntax and Compose configuration checks passed. The latest offline evaluation artifact is `reports/evaluation.json`.

A subsequent live Gemini diagnostic could not reach the provider, including outside the restricted execution sandbox. This supersedes the earlier connectivity status, but does not establish the cause of the network failure. Full successful live generation, installed Tesseract execution and container runtime remain unverified. Screenshots show the offline verification session.
