"""Fresh synthetic scenarios; does not read or write the application database."""

import json
from pathlib import Path
from labfix.engine import run_workflow
from labfix.storage import DEFAULT_SEED

CASES = [
    (
        "Duplicate",
        dict(equipment="PC-01", description="No internet"),
        False,
        "awaiting_approval",
        "link",
        "Medium",
        1,
    ),
    (
        "Projector",
        dict(
            lab="Lab 2",
            equipment="PJ-02",
            description="Projector display failed",
            class_affected=True,
        ),
        False,
        "awaiting_approval",
        "create",
        "High",
        1,
    ),
    ("Critic retry", {}, True, "awaiting_approval", "create", "Medium", 2),
    (
        "Network incident",
        dict(equipment="PC-05", description="No internet"),
        False,
        "awaiting_approval",
        "create",
        "High",
        1,
    ),
    (
        "Unknown issue",
        dict(description="It is broken"),
        False,
        "needs_information",
        None,
        None,
        0,
    ),
    (
        "Ambiguous",
        dict(description="Python and internet fail"),
        False,
        "needs_information",
        None,
        None,
        0,
    ),
    ("Wrong lab", dict(lab="Lab 2"), False, "needs_information", None, None, 0),
    ("Blank", dict(description=""), False, "needs_information", None, None, 0),
    (
        "Explicit category",
        dict(description="It fails", category="software"),
        False,
        "awaiting_approval",
        "create",
        "Medium",
        1,
    ),
    (
        "Other lab network",
        dict(lab="Lab 2", equipment="PC-10", description="No internet"),
        False,
        "awaiting_approval",
        "create",
        "Medium",
        1,
    ),
]


def evaluate():
    results = []
    for name, changes, inject, status, action, priority, attempts in CASES:
        data = json.loads(DEFAULT_SEED.read_text(encoding="utf-8"))
        req = dict(
            lab="Lab 1",
            equipment="PC-08",
            description="Python software is missing",
            category="auto",
            class_affected=False,
        )
        req.update(changes)
        s = run_workflow(req, data, inject_error=inject)
        p = s.get("proposal", {})
        actual = (s["status"], p.get("action"), p.get("priority"), s["attempts"])
        expected = (status, action, priority, attempts)
        results.append(
            dict(
                scenario=name,
                passed=actual == expected,
                expected=expected,
                actual=actual,
            )
        )
    return results


if __name__ == "__main__":
    results = evaluate()
    for r in results:
        print(
            ("PASS" if r["passed"] else "FAIL")
            + "  "
            + r["scenario"]
            + "  "
            + str(r["actual"])
        )
    print(
        f"\n{sum(r['passed'] for r in results)}/{len(results)} synthetic scenarios matched the defined expectations."
    )
    print("Functional checks only; no real-world accuracy or time-saving claim.")
    raise SystemExit(0 if all(r["passed"] for r in results) else 1)
