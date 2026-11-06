# API examples

The examples use curl syntax. Supply your own token and replace IDs/digests from actual responses.

```shell
curl http://127.0.0.1:8000/api/incidents -H "Authorization: Bearer demo-reader-change-me"

curl http://127.0.0.1:8000/api/runs \
  -H "Authorization: Bearer demo-reader-change-me" \
  -H "Content-Type: application/json" \
  -d '{"question":"Which enterprise customers were affected by last week\u0027s login incident?","incident_id":"acme:INC-1042"}'

curl http://127.0.0.1:8000/api/proposals/PROPOSAL_ID/decision \
  -H "Authorization: Bearer demo-admin-change-me" \
  -H "Content-Type: application/json" \
  -d '{"digest":"EXACT_64_CHARACTER_DIGEST_FROM_PROPOSAL","decision":"approve"}'
```

`POST /api/runs/stream` accepts the same JSON as `/api/runs` and returns SSE `progress`, `result`, and `error` events. Only the terminal `result` contains findings; a stream error does not imply any tickets were created. Analyses produce drafts only.

| Endpoint | Authorization | Behavior |
|---|---|---|
| `GET /health` | Public | SQL connectivity and selected retrieval mode |
| `GET /api/me` | Analyst/operator | Current role, tenant, retrieval settings |
| `GET /api/incidents` | Analyst/operator | Incident selector |
| `GET /api/search?q=...` | Analyst/operator | Scoped parent contexts with child matches; optional kinds/document_ids/min_revision filters |
| `POST /api/answers` | Analyst/operator | Gemini answer with citations and a separate support check |
| `GET /api/sources/{id}` | Analyst/operator | Current visible document |
| `POST /api/runs` | Analyst/operator | Analyze and persist a proposal |
| `POST /api/runs/stream` | Analyst/operator | Stream bounded workflow progress |
| `GET /api/runs/{id}` | Analyst/operator | Owned saved evidence snapshot; current document-access recheck |
| `POST /api/proposals/{id}/decision` | Operator | Approve exact digest and execute, or reject |
| `GET /api/tickets` | Analyst/operator | Local ticket ledger |
| `GET /api/audit` | Operator | Most recent 200 audit events |

The decision endpoint accepts `approve` or `reject`. It returns HTTP 409 for stale, expired, altered, or incompatible already-decided proposals. Retrying an already executed approval returns a successful receipt. Invalid credentials return 401; insufficient role returns 403; out-of-scope resources return 404.

Approval and execution are one transaction for this local ledger. There is no separate endpoint an agent can use to skip approval. `/health` is a liveness/SQL check; it does not confirm the OpenSearch index or model downloads are ready.

## Conversation and monitoring APIs

`POST /api/runs`, `/api/runs/stream`, and `/api/answers` accept `conversation_id` and return it. Omit it to start a conversation. The incident UI passes the ID automatically until New conversation or a refresh.

```json
{"question":"Prepare follow-ups for those customers","conversation_id":"ID_FROM_PREVIOUS_RESPONSE"}
```

`GET /api/conversations/{id}` is tenant/actor scoped and returns up to 100 user turns. `GET /api/metrics` is operator-only and returns count, p50_ms, p95_ms, error_rate and the latest 200 detailed operation records. Unknown costs are JSON null.

A filtered search example is `/api/search?q=SAML&kinds=product&document_ids=acme:KB-208&min_revision=1`. Repeat kinds/document_ids for multiple allowed values. These filters narrow server-authorized documents; they cannot grant access.
