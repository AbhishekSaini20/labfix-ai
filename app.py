"""Run: python -m streamlit run app.py"""

import csv
import io
import json
import os
from pathlib import Path
import streamlit as st
from labfix.engine import run_workflow, OPEN
from labfix.storage import Store

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="LabFix AI", page_icon="🛠️", layout="wide")

st.markdown(
    """
    <style>
    .stApp {
        background: #F4F7FB;
        color: #172B4D;
    }

    .block-container {
        max-width: 1450px;
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    h1, h2, h3 {
        color: #142B4E;
        font-weight: 700;
    }

    [data-testid="stMetric"] {
        background: white;
        border: 1px solid #DCE5F0;
        border-radius: 14px;
        padding: 18px;
        box-shadow: 0 2px 8px rgba(20, 40, 80, 0.05);
    }

    [data-testid="stSidebar"] {
        background: #EAF0F8;
    }

    .stButton > button {
        border-radius: 9px;
        min-height: 42px;
        font-weight: 600;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
    }

    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 10px 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

store = Store(os.environ.get("LABFIX_DB", str(ROOT / "runtime" / "labfix.db")))
data, revision = store.snapshot()
tech_names = {t["id"]: t["name"] for t in data["technicians"]}
DEMOS = {
    "Duplicate complaint": dict(
        description="Computer 1 has no internet.",
        lab="Lab 1",
        equipment="PC-01",
        category="auto",
        class_affected=False,
        inject=False,
    ),
    "Urgent projector failure": dict(
        description="The projector display is not working. A class starts in 15 minutes.",
        lab="Lab 2",
        equipment="PJ-02",
        category="auto",
        class_affected=True,
        inject=False,
    ),
    "Critic catches wrong assignment": dict(
        description="Python software is missing on Computer 8.",
        lab="Lab 1",
        equipment="PC-08",
        category="auto",
        class_affected=False,
        inject=True,
    ),
    "Possible lab network incident": dict(
        description="Computer 5 has no internet.",
        lab="Lab 1",
        equipment="PC-05",
        category="auto",
        class_affected=False,
        inject=False,
    ),
    "Missing information": dict(
        description="It is broken.",
        lab="Lab 1",
        equipment="PC-08",
        category="auto",
        class_affected=False,
        inject=False,
    ),
}
with st.sidebar:
    st.title("🛠️ LabFix AI")
    st.caption("College lab maintenance coordinator")
    st.info(
        "Offline mode · deterministic mock agents\n\nSynthetic data only. No API key required."
    )
    demo = st.selectbox("Choose a demo", list(DEMOS))
    if st.button("Load demo", width="stretch"):
        st.session_state.update(DEMOS[demo])
        st.session_state.pop("workflow", None)
        st.session_state.pop("saved", None)
    st.divider()
    st.caption(
        "A proposal changes ticket data only after coordinator approval. All agents share structured workflow state."
    )
    st.caption("Seed: 17 assets · 4 technicians · 20 tickets · 8 knowledge entries")
st.title("Lab issues, investigated and validated")
st.write(
    "Report a problem, inspect the agent decisions, then approve the proposed action."
)
cols = st.columns(4)
cols[0].metric("Open tickets", sum(t["status"] in OPEN for t in data["tickets"]))
cols[1].metric(
    "High priority",
    sum(t["status"] in OPEN and t["priority"] == "High" for t in data["tickets"]),
)
cols[2].metric("Linked repeat reports", sum(t["reports"] - 1 for t in data["tickets"]))
cols[3].metric("Approved workflows", len(data.get("audit", [])))
report_tab, flow_tab, dashboard_tab, about_tab = st.tabs(
    ["Report & approve", "Agent workflow", "Ticket dashboard", "Architecture & data"]
)
with report_tab:
    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("Report a lab issue")
        lab = st.selectbox("Lab", ["Lab 1", "Lab 2"], key="lab")
        assets = [e["id"] for e in data["equipment"] if e["lab"] == lab]
        if st.session_state.get("equipment") not in assets:
            st.session_state["equipment"] = assets[0]
        eq = st.selectbox(
            "Equipment",
            assets,
            key="equipment",
            format_func=lambda v: next(
                e["label"] + " (" + v + ")" for e in data["equipment"] if e["id"] == v
            ),
        )
        description = st.text_area(
            "What is wrong?",
            key="description",
            height=120,
            placeholder="Example: Computer 5 has no internet.",
        )
        category = st.selectbox(
            "Issue category",
            ["auto", "network", "display", "software", "hardware"],
            key="category",
        )
        affected = st.checkbox(
            "A class or exam is affected / starts within 30 minutes",
            key="class_affected",
        )
        inject = st.checkbox(
            "Demo: inject an incorrect technician assignment", key="inject"
        )
        if st.button("Run agent workflow", type="primary", width="stretch"):
            st.session_state["workflow"] = run_workflow(
                dict(
                    lab=lab,
                    equipment=eq,
                    description=description,
                    category=category,
                    class_affected=affected,
                ),
                data,
                revision,
                inject_error=inject,
            )
            st.session_state.pop("saved", None)
    with right:
        st.subheader("Coordinator review")
        state = st.session_state.get("workflow")
        if st.session_state.get("saved"):
            st.success("Approved and saved: " + st.session_state["saved"])
        elif state:
            if state["status"] == "needs_information":
                st.warning("The Planner needs more information.")
                for q in state["questions"]:
                    st.write("• " + q)
            elif state["status"] == "blocked":
                st.error("Validation failed. No ticket was saved.")
                st.write(state["validation_errors"])
            else:
                p = state["proposal"]
                st.success(f"Critic passed after {state['attempts']} attempt(s).")
                st.write("**Reported issue:** " + p["description"])
                st.write(
                    f"**Action:** {'Link to '+p['target_id'] if p['action']=='link' else 'Create '+p['kind']}"
                )
                st.write(
                    f"**Location:** {p['lab']} / {p['equipment']} · **Priority:** {p['priority']}"
                )
                st.write(
                    "**Technician:** "
                    + tech_names.get(
                        p["technician_id"], "Unassigned — coordinator action required"
                    )
                )
                if p["needs_manual_assignment"]:
                    st.warning(
                        "No eligible technician is available. Approval creates an explicitly unassigned ticket."
                    )
                if p["kind"] == "incident":
                    st.info(
                        "Possible common network issue, subject to coordinator review. Related tickets: "
                        + ", ".join(p["related_ids"])
                    )
                st.write("**Approved troubleshooting**")
                for step in p["steps"]:
                    st.write("• " + step)
                st.caption("Knowledge references: " + ", ".join(p["knowledge_ids"]))
                if st.button("Approve & save", type="primary", width="stretch"):
                    try:
                        st.session_state["saved"] = store.approve(state)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        else:
            st.info(
                "Load a demo from the sidebar or submit your own issue. The proposal will appear here."
            )
with flow_tab:
    state = st.session_state.get("workflow")
    if not state:
        st.info("Run a workflow to inspect the agents and their tool observations.")
    else:
        st.subheader("Decision and tool log")
        st.caption(
            f"Mode: {state['mode']} · Status: {state['status']} · Attempts: {state['attempts']}"
        )
        for e in state["trace"]:
            with st.expander(
                f"{e['step']:02d}  {e['agent']} — {e['action']}",
                expanded=e["agent"] == "Critic",
            ):
                st.json(e["details"])
        st.download_button(
            "Download workflow JSON",
            json.dumps(state, indent=2),
            "labfix_workflow.json",
            "application/json",
        )
with dashboard_tab:
    st.subheader("Maintenance ticket dashboard")

    search_text = st.text_input(
        "Search tickets",
        placeholder="Search by ticket ID, equipment or category",
        key="dashboard_search",
    )

    filter_col1, filter_col2 = st.columns(2)

    with filter_col1:
        status = st.selectbox(
            "Filter status",
            ["All", "Open", "In progress", "Resolved"],
            key="dashboard_status",
        )

    with filter_col2:
        priority_filter = st.selectbox(
            "Filter priority",
            ["All", "High", "Medium"],
            key="dashboard_priority",
        )

    fields = [
        "id",
        "lab",
        "equipment",
        "category",
        "priority",
        "status",
        "kind",
        "technician_id",
        "reports",
    ]

    search_term = search_text.strip().lower()

    rows = [
        {k: t.get(k) for k in fields}
        for t in data["tickets"]
        if (
            status == "All" or t["status"] == status
        )
        and (
            priority_filter == "All"
            or t["priority"] == priority_filter
        )
        and (
            search_term in (
                str(t.get("id", ""))
                + " "
                + str(t.get("equipment", ""))
                + " "
                + str(t.get("category", ""))
                + " "
                + str(t.get("lab", ""))
            ).lower()
        )
    ]

    st.caption(f"Showing {len(rows)} matching tickets")

    st.dataframe(rows, width="stretch", hide_index=True)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    st.download_button(
        "Export filtered tickets", output.getvalue(), "labfix_tickets.csv", "text/csv"
    )
    st.caption(
        "Possible incidents link related reports for review. Existing tickets remain open and retain their original assignments."
    )
    with st.expander("Approved workflow audit history"):
        st.json(data.get("audit", []))
with about_tab:
    st.subheader("Four agents, shared state, a bounded correction loop")
    architecture = ROOT / "docs" / "architecture.png"
    if architecture.exists():
        st.image(
            str(architecture),
            caption="Tools read local data; approval commits to SQLite.",
        )
    st.write(
        "Planner checks inputs and selects actions. Investigation gathers evidence. Executor prepares a proposal. Critic checks rules and returns feedback. The Planner retries a failed proposal once, then blocks it if it still fails."
    )
    st.warning(
        "This is a deterministic mock-model PoC, as permitted by the assignment. It does not use a trained language model or perform real hardware diagnostics."
    )
    with st.expander("Technicians and capacity"):
        st.dataframe(data["technicians"], hide_index=True, width="stretch")
    with st.expander("Approved knowledge base"):
        st.json(data["knowledge"])
    st.caption(
        "Limitations: keyword routing, exact equipment/category duplicates, synthetic workloads, no login, no real notifications, no ticket lifecycle editor. See the project guide for evaluation and future scope."
    )
