import os
import tempfile
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest


class UITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("LABFIX_DB")
        os.environ["LABFIX_DB"] = str(Path(self.tmp.name) / "ui.db")
        self.app = AppTest.from_file(
            str(Path(__file__).resolve().parents[1] / "app.py")
        ).run(timeout=20)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("LABFIX_DB", None)
        else:
            os.environ["LABFIX_DB"] = self.old
        self.tmp.cleanup()

    def button(self, label):
        return next(b for b in self.app.button if b.label == label)

    def test_26_app_loads_and_duplicate_approves(self):
        self.assertFalse(self.app.exception)
        self.button("Load demo").click().run()
        self.button("Run agent workflow").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(
            self.app.session_state["workflow"]["proposal"]["target_id"], "LF-001"
        )
        self.button("Approve & save").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["saved"], "LF-001")

    def test_27_projector_demo_changes_lab(self):
        self.app.sidebar.selectbox[0].select("Urgent projector failure").run()
        self.button("Load demo").click().run()
        self.button("Run agent workflow").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(
            self.app.session_state["workflow"]["proposal"]["priority"], "High"
        )

    def test_28_critic_demo_retries(self):
        self.app.sidebar.selectbox[0].select("Critic catches wrong assignment").run()
        self.button("Load demo").click().run()
        self.button("Run agent workflow").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["workflow"]["attempts"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
