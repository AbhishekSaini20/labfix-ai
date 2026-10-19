"""Local SQLite persistence with atomic approval, revision checks and replay protection."""

import json
import sqlite3
from pathlib import Path
from .engine import CriticAgent, RANK

DEFAULT_SEED = Path(__file__).resolve().parents[1] / "data" / "seed.json"


class StaleProposal(ValueError):
    pass


class Store:
    def __init__(self, path, seed_path=DEFAULT_SEED):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER, payload TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS approvals (workflow_id TEXT PRIMARY KEY, ticket_id TEXT)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO state VALUES (1, 0, ?)",
                (Path(seed_path).read_text(encoding="utf-8"),),
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def snapshot(self):
        with self.connect() as conn:
            rev, payload = conn.execute(
                "SELECT revision,payload FROM state WHERE id=1"
            ).fetchone()
            return json.loads(payload), rev

    def approve(self, state):
        if state.get("status") != "awaiting_approval":
            raise ValueError("Only a validated proposal can be approved.")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                "SELECT ticket_id FROM approvals WHERE workflow_id=?",
                (state["workflow_id"],),
            ).fetchone()
            if prior:
                return prior[0]
            rev, payload = conn.execute(
                "SELECT revision,payload FROM state WHERE id=1"
            ).fetchone()
            if rev != state["revision"]:
                raise StaleProposal(
                    "Data changed after analysis. Run the workflow again before approving."
                )
            data = json.loads(payload)
            errors = CriticAgent().validate(state, data)
            if errors:
                raise ValueError("Approval validation failed: " + "; ".join(errors))
            p = state["proposal"]
            if p["action"] == "link":
                ticket = next(t for t in data["tickets"] if t["id"] == p["target_id"])
                ticket["reports"] += 1
                if RANK[p["priority"]] > RANK[ticket["priority"]]:
                    ticket["priority"] = p["priority"]
            else:
                next_id = (
                    max([int(t["id"].split("-")[1]) for t in data["tickets"]] + [0]) + 1
                )
                ticket = {
                    k: p[k]
                    for k in [
                        "lab",
                        "equipment",
                        "category",
                        "description",
                        "priority",
                        "kind",
                        "related_ids",
                        "technician_id",
                    ]
                }
                ticket.update(
                    id=f"LF-{next_id:03d}",
                    status="Open",
                    reports=1,
                    created_at=state["created_at"],
                )
                data["tickets"].append(ticket)
            ticket.setdefault("report_history", []).append(
                {
                    "description": state["request"]["description"],
                    "equipment": state["request"]["equipment"],
                    "class_affected": state["request"].get("class_affected", False),
                    "created_at": state["created_at"],
                    "workflow_id": state["workflow_id"],
                }
            )
            data.setdefault("audit", []).append(
                {
                    "workflow_id": state["workflow_id"],
                    "ticket_id": ticket["id"],
                    "action": p["action"],
                    "trace": state["trace"],
                }
            )
            conn.execute(
                "UPDATE state SET revision=?,payload=? WHERE id=1",
                (rev + 1, json.dumps(data)),
            )
            conn.execute(
                "INSERT INTO approvals VALUES (?,?)",
                (state["workflow_id"], ticket["id"]),
            )
            return ticket["id"]
