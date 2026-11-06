# Run this project in VS Code

## What you need

- Python 3.12 (recommended), VS Code, and an internet connection.
- Your Gemini key in the root `.env` file.
- The Microsoft Python and Python Debugger VS Code extensions if you want to use F5.

You do **not** need a database account, PostgreSQL installation, Docker, a GPU, or local AI model downloads for this setup.

## Which file do I run?

Run **`run.cmd`** from the project root, or press **F5**. Both launch:

```text
python -m uvicorn copilot.api:app --host 127.0.0.1 --port 8000
```

`copilot/api.py` defines the FastAPI application. Uvicorn serves it and the browser interface. Do not run individual modules such as `gemini.py` or `workflow.py`, and do not double-click `index.html`: those files need the running API.

## Exact steps

1. In VS Code choose **File > Open Folder** and select `Enterprise Knowledge Copilot`.
2. Open **Terminal > New Terminal**.
3. For the first setup, run ` .\setup.cmd ` (without the spaces). It installs dependencies and initializes the database. Running setup again preserves `.env` and existing records.
4. Check that `.env` contains `GEMINI_API_KEY=...`. Never paste this key into the browser's login box. Do not show `.env` in your recording.
5. Run ` .\run.cmd `, then open **http://127.0.0.1:8000** in your browser.
6. Connect using `COPILOT_ADMIN_TOKEN` from `.env`. The starter local token is `demo-admin-change-me`.
7. Select the login incident from the dropdown and click **Investigate**. Selecting it explicitly works even when the seeded incident is no longer from last week.
8. Inspect the sources, uncertainty, generated answer and proposed tickets. Click **Approve & create** when ready. Check **Follow-up tickets** and **Activity log**.

To stop the app, press **Ctrl+C** in its terminal. On the next run, just use ` .\run.cmd ` again. Restart whenever you change `.env`.

## F5 alternative

After setup, press Ctrl+Shift+P > **Python: Select Interpreter** and choose `.venv\Scripts\python.exe` in this folder. Open Run and Debug, select **Run Copilot (Gemini + SQLite)**, and press F5. The supplied `.vscode/launch.json` starts the same server and loads `.env`.

Run one server at a time. If port 8000 is busy, stop the previous terminal/debug run before starting another.

## What happens to the database?

SQLite stores everything in **`copilot.db`** in this folder. The app creates its tables and inserts fictional customer, subscription, incident and document records automatically. It also stores saved analyses, approval decisions, tickets, audit events and cached Gemini embeddings. You do not run SQL manually. Restarting preserves these records.

The old `demo` wording describes this fictional dataset and shared development credentials. It does not mean Gemini is mocked in the running app. The UI now shows a single **Sample data** badge. Automated tests do mock Gemini so running tests does not spend quota.

## API model configuration

The initial `gemini-2.5-flash` request was rejected by Google's API as unavailable to new users. The error explicitly recommended `gemini-3.8-flash`, so the current configuration uses that model. `gemini-embedding-001` remains the embedding model. Model access/quota can vary; configuration is editable without changing code.

For a hidden-key diagnostic:

```powershell
.\.venv\Scripts\python -m copilot.cli doctor --live
```

This makes two small Gemini API requests. For local checks without external requests:

```powershell
.\.venv\Scripts\python -m copilot.cli doctor
.\.venv\Scripts\python -m pytest -q
```

The first investigation is slower while embeddings are created. A full incident run makes around five generation calls plus uncached embedding calls. A rate-limit error means wait and check your Google project quota; repeating quickly can make the limit worse. No free-tier guarantee is made by this application.

For the portfolio recording, use [the recording guide](docs/recording-guide.md).

## Earlier live API check

The key and embedding endpoint were verified. Generation returned HTTP 503 during the live check, explicitly reporting temporary high demand. The app can be started, but successful answer generation still depends on provider availability. Run the live doctor check before recording; the UI reports a provider failure without creating tickets.

## Conversation history and monitoring

Restart with `.\run.cmd`; new memory, document-permission and monitoring tables initialize automatically. No database recreation is needed. The incident view now keeps conversation context within the browser tab. Try “Prepare follow-ups for those customers,” then use New conversation to clear the context pointer. Open Monitoring as the operator for latency, verification signals and cost estimates. Costs remain Unknown until usage and your configured prices are available.

The README now documents all 15 requested capabilities, exact implementation scope, configuration, ingestion/OCR, permissions, APIs, MCP, Docker, evaluation and limitations. Run the reproducible offline evaluation with:

```powershell
.\.venv\Scripts\python -m copilot.cli evaluate --offline --output reports/evaluation.json
```
