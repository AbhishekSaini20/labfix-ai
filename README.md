# LabFix AI

Offline, deterministic multi-agent workflow for college lab maintenance
(Planner -> Investigation -> Executor -> Critic, then coordinator approval).
No LLM, cloud service or API key. Synthetic data only.

## Run on Windows
Install Python 3.11 or 3.12 (tick "Add python.exe to PATH"), then double-click
`START_WINDOWS.bat`. The first run creates `.venv` and installs Streamlit 1.50.0
(internet needed once). The app opens in your browser.

Manual way:
    py -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python -m streamlit run app.py

## Run the checks
    python -m unittest discover -s tests -v     (28 tests: engine, storage, UI)
    python evaluate.py                          (10 synthetic scenarios)

## Folder map
- app.py            Streamlit screen (report, agent workflow, dashboard, architecture)
- labfix/engine.py  the four agents, tools, bounded retry
- labfix/storage.py SQLite store: atomic approval, revision check, replay protection
- data/seed.json    17 assets, 4 technicians, 20 tickets, 8 knowledge entries
- docs/architecture.png  diagram shown in the "Architecture & data" tab
- tests/            unit + UI tests
- runtime/          created automatically; holds labfix.db (delete it to reset)

## Demos (sidebar)
Duplicate complaint, Urgent projector failure, Critic catches wrong assignment,
Possible lab network incident, Missing information.

## Limitations
Keyword routing, exact equipment/category duplicates, synthetic workloads, no
login, no notifications, no ticket lifecycle editor. Mock-model PoC: no real
hardware diagnostics.
