import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from labfix.engine import run_workflow, CriticAgent
from labfix.storage import Store, DEFAULT_SEED, StaleProposal


def request(**changes):
    r = dict(
        description="Python software is missing.",
        lab="Lab 1",
        equipment="PC-08",
        category="auto",
        class_affected=False,
    )
    r.update(changes)
    return r


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(DEFAULT_SEED.read_text())

    def test_01_new_software_assignment(self):
        s = run_workflow(request(), self.data)
        self.assertEqual(s["status"], "awaiting_approval")
        self.assertEqual(s["proposal"]["technician_id"], "TECH-03")

    def test_02_duplicate_links_open_ticket(self):
        self.assertEqual(
            run_workflow(
                request(equipment="PC-01", description="No internet"), self.data
            )["proposal"]["target_id"],
            "LF-001",
        )

    def test_03_closed_ticket_is_not_duplicate(self):
        self.assertEqual(
            run_workflow(request(), self.data)["proposal"]["action"], "create"
        )

    def test_04_class_impact_is_high_priority(self):
        p = run_workflow(
            request(
                lab="Lab 2",
                equipment="PJ-02",
                description="Projector display failed",
                class_affected=True,
            ),
            self.data,
        )["proposal"]
        self.assertEqual(p["priority"], "High")
        self.assertEqual(p["technician_id"], "TECH-02")

    def test_05_fault_is_rejected_and_corrected(self):
        s = run_workflow(request(), self.data, inject_error=True)
        self.assertEqual(s["attempts"], 2)
        self.assertEqual(
            [e["details"]["passed"] for e in s["trace"] if e["agent"] == "Critic"],
            [False, True],
        )
        self.assertEqual(s["proposal"]["technician_id"], "TECH-03")

    def test_06_retry_limit_blocks(self):
        self.assertEqual(
            run_workflow(request(), self.data, inject_error=True, max_attempts=1)[
                "status"
            ],
            "blocked",
        )

    def test_07_unknown_issue_pauses(self):
        s = run_workflow(request(description="It is broken"), self.data)
        self.assertEqual(s["status"], "needs_information")
        self.assertNotIn("proposal", s)

    def test_08_missing_description_pauses(self):
        self.assertEqual(
            run_workflow(request(description=""), self.data)["status"],
            "needs_information",
        )

    def test_09_mismatched_lab_pauses(self):
        self.assertEqual(
            run_workflow(request(lab="Lab 2"), self.data)["status"], "needs_information"
        )

    def test_10_ambiguous_issue_pauses(self):
        self.assertEqual(
            run_workflow(request(description="Python and internet fail"), self.data)[
                "status"
            ],
            "needs_information",
        )

    def test_11_explicit_category_resolves_ambiguity(self):
        self.assertEqual(
            run_workflow(
                request(description="It fails", category="software"), self.data
            )["status"],
            "awaiting_approval",
        )

    def test_12_no_technician_is_explicit(self):
        for t in self.data["technicians"]:
            t["available"] = False
        p = run_workflow(request(), self.data)["proposal"]
        self.assertIsNone(p["technician_id"])
        self.assertTrue(p["needs_manual_assignment"])

    def test_13_capacity_is_respected(self):
        self.data["technicians"][2]["capacity"] = 1
        self.assertIsNone(
            run_workflow(request(), self.data)["proposal"]["technician_id"]
        )

    def test_14_three_devices_trigger_incident(self):
        p = run_workflow(
            request(equipment="PC-05", description="No internet"), self.data
        )["proposal"]
        self.assertEqual(p["kind"], "incident")
        self.assertEqual(p["priority"], "High")
        self.assertEqual(p["related_ids"], ["LF-001", "LF-002"])

    def test_15_two_devices_do_not_trigger_incident(self):
        self.data["tickets"][1]["status"] = "Resolved"
        self.assertEqual(
            run_workflow(
                request(equipment="PC-05", description="No internet"), self.data
            )["proposal"]["kind"],
            "ticket",
        )

    def test_16_cross_lab_reports_do_not_group(self):
        self.assertEqual(
            run_workflow(
                request(lab="Lab 2", equipment="PC-10", description="No internet"),
                self.data,
            )["proposal"]["kind"],
            "ticket",
        )

    def test_17_unsupported_guidance_rejected(self):
        s = run_workflow(request(), self.data)
        s["proposal"]["steps"].append("Invented instruction")
        self.assertTrue(CriticAgent().validate(s, self.data))

    def test_18_low_priority_tampering_rejected(self):
        s = run_workflow(request(class_affected=True), self.data)
        s["proposal"]["priority"] = "Low"
        self.assertTrue(CriticAgent().validate(s, self.data))

    def test_19_workflow_does_not_mutate_data(self):
        before = deepcopy(self.data)
        run_workflow(request(), self.data)
        self.assertEqual(before, self.data)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.db")
        self.data, self.rev = self.store.snapshot()

    def tearDown(self):
        self.tmp.cleanup()

    def test_20_approval_persists_once(self):
        s = run_workflow(request(), self.data, self.rev)
        first = self.store.approve(s)
        self.assertEqual(self.store.approve(s), first)
        data, rev = self.store.snapshot()
        self.assertEqual(len(data["tickets"]), 21)
        self.assertEqual(rev, 1)
        self.assertEqual(len(data["audit"]), 1)

    def test_21_duplicate_increments_and_preserves_report(self):
        s = run_workflow(
            request(equipment="PC-01", description="No internet", class_affected=True),
            self.data,
            self.rev,
        )
        self.store.approve(s)
        data, _ = self.store.snapshot()
        self.assertEqual(len(data["tickets"]), 20)
        self.assertEqual(data["tickets"][0]["reports"], 2)
        self.assertEqual(data["tickets"][0]["priority"], "High")
        self.assertEqual(len(data["tickets"][0]["report_history"]), 1)

    def test_22_stale_proposal_is_rejected(self):
        one = run_workflow(request(), self.data, self.rev)
        two = run_workflow(request(equipment="PC-07"), self.data, self.rev)
        self.store.approve(one)
        with self.assertRaises(StaleProposal):
            self.store.approve(two)

    def test_23_revalidate_before_commit(self):
        s = run_workflow(request(), self.data, self.rev)
        s["proposal"]["technician_id"] = "TECH-01"
        with self.assertRaises(ValueError):
            self.store.approve(s)
        self.assertEqual(self.store.snapshot()[1], 0)

    def test_24_blocked_state_cannot_commit(self):
        s = run_workflow(request(description=""), self.data, self.rev)
        with self.assertRaises(ValueError):
            self.store.approve(s)

    def test_25_incident_absorbs_next_lab_network_report(self):
        s = run_workflow(
            request(equipment="PC-05", description="No internet"), self.data, self.rev
        )
        incident_id = self.store.approve(s)
        data, rev = self.store.snapshot()
        s = run_workflow(
            request(equipment="PC-07", description="No internet"), data, rev
        )
        self.assertEqual(s["proposal"]["target_id"], incident_id)
        self.assertEqual(s["proposal"]["priority"], "High")


if __name__ == "__main__":
    unittest.main(verbosity=2)
