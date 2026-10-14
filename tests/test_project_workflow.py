import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch
import unittest

from ascendra.project_workflow import (
    Step, WorkflowLimits, run_plan, run_project_workflow, validate_plan,
)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "run"

    @staticmethod
    def generate(description, path):
        path.mkdir()
        (path / "index.html").write_text("broken")

    @staticmethod
    def verify(path):
        passed = (path / "index.html").read_text() == "fixed"
        return {"passed": passed, "checks": [{"name": "fixture content", "passed": passed}]}

    def test_repair_preserves_candidates_and_evidence(self):
        def repair(description, previous, evidence, path):
            self.assertFalse(evidence["passed"])
            path.mkdir()
            (path / "index.html").write_text("fixed")
        result = run_project_workflow("task", self.root, generate=self.generate,
                                      verify=self.verify, repair=repair)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["model_calls"], 2)
        self.assertEqual((self.root / "candidate-000/index.html").read_text(), "broken")
        self.assertFalse(result["published"])
        self.assertEqual(json.loads((self.root / "workflow-result.json").read_text()), result)

    def test_budget_and_no_false_success(self):
        result = run_project_workflow("task", self.root, generate=self.generate,
            verify=self.verify, repair=lambda d, p, v, n: self.generate(d, n),
            limits=WorkflowLimits(max_repairs=3, max_model_calls=2))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "model_call_budget_exhausted")
        self.assertEqual(result["model_calls"], 2)
        self.assertIsNone(result["artifact"])

    def test_cancel_before_dispatch(self):
        result = run_project_workflow("task", self.root, generate=self.generate,
                                      verify=self.verify, cancelled=lambda: True)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["model_calls"], 0)

    def test_cancel_after_generation_never_verifies(self):
        flag = threading.Event()
        def generate(d, p):
            self.generate(d, p)
            flag.set()
        result = run_project_workflow("task", self.root, generate=generate,
            verify=lambda p: self.fail("verification after cancellation"), cancelled=flag.is_set)
        self.assertEqual(result["status"], "cancelled")

    def test_invalid_evidence_rejected(self):
        result = run_project_workflow("task", self.root, generate=self.generate,
                                      verify=lambda p: {"passed": True, "checks": []})
        self.assertEqual(result["status"], "failed")

    def test_mutating_verifier_rejected(self):
        def verify(p):
            (p / "index.html").write_text("fixed")
            return self.verify(p)
        result = run_project_workflow("task", self.root, generate=self.generate, verify=verify)
        self.assertEqual(result["status"], "failed")

    def test_time_budget_after_generation(self):
        with patch("ascendra.project_workflow.time.monotonic", side_effect=[0, 0, 2, 2]):
            result = run_project_workflow("task", self.root, generate=self.generate,
                verify=lambda p: self.fail("timeout must prevent verification"),
                limits=WorkflowLimits(max_seconds=1))
        self.assertEqual(result["reason"], "time_budget_exhausted")

    def test_repair_cannot_mutate_prior_artifact(self):
        def repair(d, previous, evidence, path):
            (previous / "index.html").write_text("tampered")
            self.generate(d, path)
        result = run_project_workflow("task", self.root, generate=self.generate,
                                      verify=self.verify, repair=repair)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["attempts"][-1]["error_type"], "ValueError")

    def test_existing_destination_never_overwritten(self):
        self.root.mkdir()
        marker = self.root / "keep"
        marker.write_text("original")
        with self.assertRaises(FileExistsError):
            run_project_workflow("task", self.root, generate=self.generate, verify=self.verify)
        self.assertEqual(marker.read_text(), "original")

    def test_real_parallel_steps_and_dependency_order(self):
        barrier = threading.Barrier(2)
        def execute(step, output, dependencies):
            if step.id in {"a", "b"}:
                barrier.wait(timeout=5)
            else:
                self.assertEqual(set(dependencies), {"a", "b"})
                self.assertTrue(all((p / "result").exists() for p in dependencies.values()))
            (output / "result").write_text(step.id)
        result = run_plan([Step("a"), Step("b"), Step("c", ("a", "b"))],
                          self.root, execute=execute, max_agents=2)
        self.assertEqual(result["status"], "completed")

    def test_failed_prerequisite_blocks_descendants(self):
        def execute(step, output, dependencies):
            if step.id == "a":
                raise RuntimeError("failure")
            self.fail("dependent must not execute")
        result = run_plan([Step("a"), Step("b", ("a",)), Step("c", ("b",))],
                          self.root, execute=execute)
        self.assertEqual(result["steps"], {"a": "failed", "b": "blocked", "c": "blocked"})

    def test_plan_validation_before_side_effects(self):
        for steps in ([Step("a", ("b",)), Step("b", ("a",))],
                      [Step("a", ("missing",))], [Step("../escape")], [Step("a"), Step("a")]):
            with self.assertRaises(ValueError):
                validate_plan(steps)
        self.assertFalse(self.root.exists())

    def test_plan_cancel(self):
        result = run_plan([Step("a")], self.root, execute=lambda *a: self.fail(), cancelled=lambda: True)
        self.assertEqual(result["steps"], {"a": "cancelled"})


if __name__ == "__main__":
    unittest.main()
