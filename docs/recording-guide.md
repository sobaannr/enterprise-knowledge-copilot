# LinkedIn workflow recording

Target length: about 2–3 minutes. This is a recording plan; the app does not publish anything to LinkedIn.

## Before recording

- Start with `run.cmd`, log in, and keep only the browser window visible.
- Keep `.env`, credentials, provider account pages and private terminal contents off screen.
- Use the provided fictional Acme Cloud data and explicitly call it sample data.
- Select the incident from the dropdown so relative dates do not affect the recording.
- Run `copilot doctor --live` before filming to check model access. Allow quota recovery between rehearsals.
- Existing tickets persist across runs. If you have already approved a rehearsal, the next run will reuse them. For a fresh recording without deleting anything, stop the server and change `.env` to `COPILOT_DATABASE_URL=sqlite:///./recording.db`, then restart. That new file seeds automatically. Restore the original URL afterward if desired.

## Suggested sequence and narration

| Time | Show | Explain |
|---|---|---|
| 0:00–0:20 | Main screen and question | “This is an enterprise knowledge and action copilot using fictional B2B company data.” |
| 0:20–0:45 | Click Investigate; progress | “Gemini rewrites the question, creates embeddings and reranks hybrid BM25/FAISS results. LangGraph coordinates the workflow.” |
| 0:45–1:15 | AI answer and source disclosures | “The answer combines documents with customer and subscription records, cites its evidence, and goes through a separate support check.” |
| 1:15–1:35 | Meridian gap and MFA conflict | “Suspected impact is distinguished from confirmed impact. Superseded security advice is flagged.” |
| 1:35–2:00 | Proposed follow-ups | “Gemini proposes a scoped function call. The server validates eligible customers and prepares drafts. No tickets exist yet.” |
| 2:00–2:20 | Approve, then ticket list | “An operator approves the exact saved content, and the application records the tickets transactionally.” |
| 2:20–2:45 | Activity log; repeat if quota allows | “Approval and execution are audited. Repeated approved proposals reuse existing customer/incident tickets.” |

Do not claim a second LLM guarantees truth, that tickets were sent to a real CRM, or that sample data represents real customers. Tickets in this version live in the local SQL ledger. The UI is a working application, while the company dataset is fictional.

## Suggested post text

Built an Enterprise Knowledge & Action Copilot with Gemini, FastAPI, LangGraph, FAISS/BM25 and SQLite.

The workflow investigates a login incident, combines cited documents with structured customer records, identifies uncertainty, and prepares account-manager follow-ups. A separate verification call checks generated claims. Human approval is required before ticket creation, with an audit trail and duplicate prevention.

This recording uses fictional company data. The next steps toward production would include individual SSO permissions, broader evaluation and an external-ticket delivery outbox.

## Show the new requirements

After the first analysis, ask “Prepare follow-ups for those customers” to show conversation context. Explain that current evidence is re-read. Open Monitoring to show latency, claim verification signals and cost availability. Show `reports/evaluation.json` with its offline configuration and small synthetic-fixture limitation. Explain parent-child retrieval, document ACL filtering and bounded query decomposition using the README diagram. Do not imply the mocked OCR tests or offline evaluation prove a successful live Gemini/OCR run.
