from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest

from ascendra.studio_store import StudioStore


class StudioStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "studio.sqlite3"
        self.store = StudioStore(self.path)
        now = datetime.now(timezone.utc).isoformat()
        self.research = {"id": "research-1", "topic": "Durable job state", "status": "complete",
                         "researched_at": now, "errors": [], "sources": [
                             {"url": "https://example.org", "title": "Evidence",
                              "excerpt": "A source excerpt.", "retrieved_at": now}]}
        self.batch = {"id": "batch-1", "research_id": "research-1", "mode": "self_improvement",
                      "recommended_id": "p0", "recommendation_reason": "Best impact",
                      "proposals": [{"id": f"p{i}", "title": f"Proposal {i}",
                                     "description": f"Implement feature {i} with rollback",
                                     "benefit": "Better reliability", "estimated_effort": "1 hour",
                                     "risks": ["Migration errors"],
                                     "acceptance_criteria": ["Independent before and after tests pass"],
                                     "source_urls": ["https://example.org"]} for i in range(3)]}
        self.store.save_research(self.research)
        self.store.save_batch(self.batch)

    def test_restart_and_immutable_snapshots(self):
        job = self.store.approve("batch-1", "p0")
        job["proposal"]["title"] = "tampered"
        other = StudioStore(self.path)
        self.assertEqual(other.list_batches(), [self.batch])
        self.assertEqual(other.get_research("research-1"), self.research)
        self.assertEqual(other.get_job(job["id"])["proposal"]["title"], "Proposal 0")
        self.assertEqual(other.list_jobs()[0]["mode"], "self_improvement")

    def test_concurrent_approval_is_idempotent_and_budget_not_enlarged(self):
        with ThreadPoolExecutor(max_workers=12) as pool:
            jobs = list(pool.map(lambda _: StudioStore(self.path).approve("batch-1", "p0"), range(30)))
        self.assertEqual(len({job["id"] for job in jobs}), 1)
        again = self.store.approve("batch-1", "p0", max_calls=1000, max_agents=50)
        self.assertEqual(again["budget"], {"max_calls": 20, "max_agents": 4})
        self.assertEqual(len(self.store.list_events(again["id"])), 1)

    def test_unknown_approval_and_limits(self):
        for batch, proposal in [("missing", "p0"), ("batch-1", "missing")]:
            with self.assertRaises(KeyError):
                self.store.approve(batch, proposal)
        for options in [{"max_calls": 0}, {"max_calls": 1001}, {"max_calls": True},
                        {"max_agents": 0}, {"max_agents": 51}, {"max_agents": 1.0}]:
            with self.assertRaises(ValueError):
                self.store.approve("batch-1", "p0", **options)
        self.assertEqual(self.store.list_jobs(), [])

    def test_transitions_audit_and_completion_is_not_verification(self):
        job = self.store.approve("batch-1", "p0")
        identifier = job["id"]
        with self.assertRaises(ValueError):
            self.store.transition(identifier, "completed")
        for state in ["running", "paused", "running"]:
            self.store.transition(identifier, state)
        done = self.store.transition(identifier, "completed", details={"tests": {"passed": 8}})
        self.assertFalse(done["verified_improvement"])
        self.assertEqual(self.store.transition(identifier, "completed"), done)
        for state in ["running", "failed", "paused", "cancelled"]:
            with self.assertRaises(ValueError):
                self.store.transition(identifier, state)
        with self.assertRaises(ValueError):
            self.store.transition(identifier, "completed", details={"tests": {"passed": 99}})
        events = StudioStore(self.path).list_events(identifier)
        self.assertEqual(len(events), 5)
        self.assertEqual(events[-1]["details"]["tests"]["passed"], 8)

    def test_all_terminal_paths(self):
        for i, terminal in enumerate(["completed", "failed", "cancelled"]):
            job = self.store.approve("batch-1", f"p{i}")
            if terminal != "cancelled":
                self.store.transition(job["id"], "running")
            self.assertEqual(self.store.transition(job["id"], terminal)["state"], terminal)

    def test_concurrent_claim_only_one_wins(self):
        identifier = self.store.approve("batch-1", "p0")["id"]
        def claim(_):
            try:
                self.store.claim_job(identifier)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=12) as pool:
            self.assertEqual(sum(pool.map(claim, range(30))), 1)
        self.assertEqual(self.store.get_job(identifier)["state"], "running")
        with self.assertRaises(ValueError):
            self.store.transition(identifier, "running")
        self.store.transition(identifier, "paused")
        with self.assertRaises(ValueError):
            self.store.claim_job(identifier)

    def test_research_required_complete_fresh_and_mode_not_overridden(self):
        for changes in [{"research_id": None}, {"mode": "arbitrary"}]:
            with self.assertRaises(ValueError):
                self.store.save_batch({**self.batch, "id": "new", **changes})
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        for i, changes in enumerate([{"status": "blocked"}, {"researched_at": old}]):
            research = {**self.research, **changes, "id": f"invalid-{i}"}
            self.store.save_research(research)
            with self.assertRaises(ValueError):
                self.store.save_batch({**self.batch, "id": f"batch-{i+2}", "research_id": research["id"]})
        malformed = json.loads(json.dumps(self.batch))
        malformed["proposals"][0]["mode"] = "project"
        with self.assertRaises(ValueError):
            self.store.save_batch(malformed)

    def test_approval_revalidates_persisted_batch(self):
        with sqlite3.connect(self.path) as db:
            malformed = {**self.batch, "mode": "arbitrary"}
            db.execute("UPDATE batches SET payload=? WHERE id=?", (json.dumps(malformed), "batch-1"))
        with self.assertRaises(ValueError):
            self.store.approve("batch-1", "p0")

    def test_immutable_records_and_invalid_batch(self):
        self.assertEqual(self.store.save_batch(self.batch), self.batch)
        with self.assertRaises(ValueError):
            self.store.save_batch({**self.batch, "mode": "other"})
        with self.assertRaises(ValueError):
            self.store.save_research({**self.research, "changed": True})
        for changes in [{"proposals": []}, {"proposals": [{"id": "p0"}] * 3},
                        {"proposals": [{"title": "No ID"}] * 3}]:
            with self.assertRaises(ValueError):
                self.store.save_batch({**self.batch, **changes, "id": "new"})
        with self.assertRaises(KeyError):
            self.store.save_batch({**self.batch, "id": "new", "research_id": "missing"})

    def test_json_bounds_types_and_aliases(self):
        for payload in [{"bad": float("nan")}, {"bad": object()}, {"bad": "x" * 65537},
                        {1: "non-string key"}, {"bad": list(range(1001))}]:
            with self.assertRaises(ValueError):
                self.store.save_research(payload)
        nested = {}
        for _ in range(22):
            nested = {"nested": nested}
        with self.assertRaises(ValueError):
            self.store.save_research(nested)
        record = self.store.save_research({"research_id": "alias"})
        self.assertEqual(record["id"], "alias")
        with self.assertRaises(ValueError):
            self.store.save_research({"id": "a", "research_id": "b"})


if __name__ == "__main__":
    unittest.main()
