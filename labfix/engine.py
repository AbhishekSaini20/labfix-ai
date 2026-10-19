"""Explicit mock agents, tool calls, decisions and bounded correction.

No LLM is used. These deterministic agents simulate an agentic workflow.
All tool observations and validation feedback are exposed in the UI.
"""

from copy import deepcopy
from datetime import datetime, timezone
import re
from uuid import uuid4

OPEN = {"Open", "In progress"}
RANK = {"Low": 0, "Medium": 1, "High": 2}
KEYWORDS = {
    "network": ["internet", "network", "wifi", "wi-fi", "connection", "connect"],
    "display": ["projector", "screen", "display", "monitor"],
    "software": ["python", "software", "install", "application", "compiler"],
    "hardware": ["keyboard", "mouse", "power", "boot", "hardware"],
}


def event(state, agent, action, details):
    state["trace"].append(
        {
            "step": len(state["trace"]) + 1,
            "agent": agent,
            "action": action,
            "details": deepcopy(details),
        }
    )


def search_existing_tickets(data, lab, equipment, category):
    return [
        t
        for t in data["tickets"]
        if t["status"] in OPEN
        and t["lab"] == lab
        and t["category"] == category
        and (
            t["equipment"] == equipment
            or (category == "network" and t["kind"] == "incident")
        )
    ]


def lookup_troubleshooting(data, category):
    return [k for k in data["knowledge"] if k["category"] == category]


def find_available_technician(data, category):
    choices = []
    for tech in data["technicians"]:
        load = sum(
            t["status"] in OPEN and t["technician_id"] == tech["id"]
            for t in data["tickets"]
        )
        if tech["available"] and category in tech["skills"] and load < tech["capacity"]:
            choices.append((load, tech["id"], tech))
    return deepcopy(min(choices, key=lambda x: (x[0], x[1]))[2]) if choices else None


def expected_priority(request, incident=False):
    return "High" if incident or request.get("class_affected", False) else "Medium"


class PlannerAgent:
    def run(self, state, data):
        req = state["request"]
        missing = []
        if not req.get("description", "").strip():
            missing.append("Describe the problem.")
        eq = next(
            (e for e in data["equipment"] if e["id"] == req.get("equipment")), None
        )
        if not eq or eq["lab"] != req.get("lab"):
            missing.append("Select equipment that belongs to the selected lab.")
        category = req.get("category", "auto")
        if category == "auto":
            text = req.get("description", "").lower()
            matches = [
                key
                for key, words in KEYWORDS.items()
                if any(re.search(r"\b" + re.escape(w) + r"\w*\b", text) for w in words)
            ]
            category = matches[0] if len(matches) == 1 else None
        if category not in KEYWORDS:
            missing.append(
                "Choose one issue category; the description is ambiguous or unsupported."
            )
        state["category"] = category
        state["questions"] = missing
        event(
            state,
            "Planner",
            "Check request and choose tools",
            {
                "category": category,
                "missing_information": missing,
                "plan": [
                    "search_existing_tickets",
                    "lookup_troubleshooting",
                    "find_available_technician if needed",
                    "validate_proposal",
                ],
            },
        )
        return not missing


class InvestigationAgent:
    def run(self, state, data):
        req, cat = state["request"], state["category"]
        matches = search_existing_tickets(data, req["lab"], req["equipment"], cat)
        knowledge = lookup_troubleshooting(data, cat)
        related = (
            [
                t
                for t in data["tickets"]
                if t["status"] in OPEN
                and t["lab"] == req["lab"]
                and t["category"] == "network"
                and t["kind"] == "ticket"
            ]
            if cat == "network"
            else []
        )
        distinct = {t["equipment"] for t in related} | {req["equipment"]}
        state["evidence"] = {
            "duplicates": [t["id"] for t in matches],
            "knowledge_ids": [k["id"] for k in knowledge],
            "related_ids": [t["id"] for t in related],
            "possible_incident": not matches
            and cat == "network"
            and len(distinct) >= 3,
        }
        event(state, "Investigation", "search_existing_tickets", {"matches": matches})
        event(state, "Investigation", "lookup_troubleshooting", {"entries": knowledge})
        event(
            state,
            "Investigation",
            "Check lab network pattern",
            {
                "distinct_equipment_count": len(distinct) if cat == "network" else 0,
                "possible_incident": state["evidence"]["possible_incident"],
                "related_ticket_ids": state["evidence"]["related_ids"],
            },
        )


class ExecutorAgent:
    def run(self, state, data, inject_error=False):
        req, ev = state["request"], state["evidence"]
        duplicate = ev["duplicates"][0] if ev["duplicates"] else None
        incident = ev["possible_incident"]
        tech = (
            find_available_technician(data, state["category"])
            if not duplicate
            else None
        )
        target = next((t for t in data["tickets"] if t["id"] == duplicate), None)
        priority = expected_priority(
            req, incident or bool(target and target["kind"] == "incident")
        )
        if target and RANK[target["priority"]] > RANK[priority]:
            priority = target["priority"]
        proposal = {
            "action": "link" if duplicate else "create",
            "target_id": duplicate,
            "lab": req["lab"],
            "equipment": req["equipment"],
            "category": state["category"],
            "description": req["description"].strip(),
            "priority": priority,
            "kind": "incident" if incident else "ticket",
            "related_ids": ev["related_ids"] if incident else [],
            "technician_id": (
                target["technician_id"] if target else (tech["id"] if tech else None)
            ),
            "knowledge_ids": ev["knowledge_ids"],
            "steps": [
                s
                for k in data["knowledge"]
                if k["id"] in ev["knowledge_ids"]
                for s in k["steps"]
            ],
            "needs_manual_assignment": not duplicate and tech is None,
        }
        if inject_error and not duplicate:
            wrong = next(
                (
                    t
                    for t in data["technicians"]
                    if state["category"] not in t["skills"]
                ),
                None,
            )
            if wrong:
                proposal["technician_id"] = wrong["id"]
                event(
                    state,
                    "Executor",
                    "DEMO: inject assignment error",
                    {"technician_id": wrong["id"]},
                )
        event(
            state,
            "Executor",
            "find_available_technician",
            {
                "selected": proposal["technician_id"],
                "policy": "Skill + availability + capacity; lowest open load",
                "existing_assignment_preserved": bool(duplicate),
            },
        )
        state["proposal"] = proposal
        event(state, "Executor", "Prepare ticket proposal", proposal)


class CriticAgent:
    def validate(self, state, data):
        p, req = state["proposal"], state["request"]
        errors = []
        if (
            p["category"] != state["category"]
            or p["lab"] != req["lab"]
            or p["equipment"] != req["equipment"]
        ):
            errors.append("Proposal does not match the request.")
        valid_eq = any(
            e["id"] == p["equipment"] and e["lab"] == p["lab"]
            for e in data["equipment"]
        )
        if not valid_eq:
            errors.append("Equipment and lab do not match.")
        matches = search_existing_tickets(data, p["lab"], p["equipment"], p["category"])
        target = next((t for t in matches if t["id"] == p["target_id"]), None)
        if p["action"] == "link" and not target:
            errors.append("Duplicate target must be a matching open ticket.")
        if p["action"] == "create" and matches:
            errors.append("A matching open ticket already exists.")
        if p["action"] not in {"create", "link"}:
            errors.append("Unsupported action.")
        minimum = expected_priority(
            req,
            p["kind"] == "incident" or bool(target and target["kind"] == "incident"),
        )
        if p["priority"] not in RANK or RANK.get(p["priority"], -1) < RANK[minimum]:
            errors.append("Priority is too low for the recorded impact.")
        if target and RANK.get(p["priority"], -1) < RANK[target["priority"]]:
            errors.append("Linking must not downgrade an existing ticket.")
        if p["action"] == "create":
            tech = next(
                (t for t in data["technicians"] if t["id"] == p["technician_id"]), None
            )
            if tech:
                load = sum(
                    t["status"] in OPEN and t["technician_id"] == tech["id"]
                    for t in data["tickets"]
                )
                if p["category"] not in tech["skills"]:
                    errors.append("Selected technician lacks the required skill.")
                if not tech["available"] or load >= tech["capacity"]:
                    errors.append("Selected technician is unavailable or at capacity.")
            elif p["technician_id"] is not None or not p["needs_manual_assignment"]:
                errors.append(
                    "Missing technician requires an explicit manual-assignment flag."
                )
            elif find_available_technician(data, p["category"]) is not None:
                errors.append(
                    "A suitable technician is available; assignment should not be skipped."
                )
            if p["kind"] == "incident":
                related = [t for t in data["tickets"] if t["id"] in p["related_ids"]]
                valid = [
                    t
                    for t in related
                    if t["lab"] == p["lab"]
                    and t["category"] == "network"
                    and t["status"] in OPEN
                    and t["kind"] == "ticket"
                ]
                if (
                    p["category"] != "network"
                    or len(valid) != len(p["related_ids"])
                    or len({t["equipment"] for t in valid} | {p["equipment"]}) < 3
                ):
                    errors.append(
                        "An incident needs open network reports from at least three distinct devices."
                    )
        allowed = lookup_troubleshooting(data, p["category"])
        if p["knowledge_ids"] != [k["id"] for k in allowed] or p["steps"] != [
            s for k in allowed for s in k["steps"]
        ]:
            errors.append(
                "Troubleshooting must exactly match approved knowledge entries."
            )
        return errors

    def run(self, state, data):
        errors = self.validate(state, data)
        state["validation_errors"] = errors
        event(
            state,
            "Critic",
            "validate_proposal",
            {
                "passed": not errors,
                "errors": errors,
                "checks": [
                    "request match",
                    "open duplicate",
                    "priority",
                    "technician eligibility",
                    "incident evidence",
                    "approved knowledge",
                ],
            },
        )
        return not errors


def run_workflow(request, data, revision=0, inject_error=False, max_attempts=2):
    if max_attempts not in {1, 2}:
        raise ValueError("Use one or two attempts.")
    state = {
        "workflow_id": str(uuid4()),
        "request": deepcopy(request),
        "trace": [],
        "revision": revision,
        "status": "planning",
        "mode": "Deterministic mock agents",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "attempts": 0,
    }
    if not PlannerAgent().run(state, data):
        state["status"] = "needs_information"
        return state
    InvestigationAgent().run(state, data)
    for attempt in range(1, max_attempts + 1):
        state["attempts"] = attempt
        ExecutorAgent().run(state, data, inject_error and attempt == 1)
        if CriticAgent().run(state, data):
            state["status"] = "awaiting_approval"
            return state
        if attempt < max_attempts:
            event(
                state,
                "Planner",
                "Revise assignment after critic feedback",
                {
                    "feedback": state["validation_errors"],
                    "next_action": "Rerun technician selection without demo fault",
                },
            )
    state["status"] = "blocked"
    return state
