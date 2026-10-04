import copy
import json
from pathlib import Path
import tempfile
import unittest

from ascendra.v4_protocol import (
    PROTOCOL, QUALITY_GATE, SELECTION_RULE, evaluate_gates, freeze_manifest,
    make_schedule, manifest_hash, validate_manifest, validate_results, verify_manifest,
)


def manifest_fixture(pilot=False):
    def task(i):
        return dict(id=f"task-{i}", difficulty="medium", public_sha256="a"*64,
                    bundle_sha256="b"*64, private_sha256="c"*64)
    return dict(protocol=PROTOCOL, experiment_id="v4-test", model="gpt-6-astra",
                reasoning="low", backend_revision=None, git_commit="test-commit",
                worktree_diff_sha256="d"*64, data_version="fixture-v1",
                checks_version="fixture-v1", prompts={"initial": "Solve public task"},
                limits={"physical_calls": 242}, environment={"sandbox": "fixture"},
                seed=2026, previous_task_ids=["already-exposed"], pilot=pilot,
                tasks={"development": [task(i) for i in range(12)],
                       "confirmation": [] if pilot else [task(i) for i in range(12, 52)]},
                selection_rule=SELECTION_RULE, gates=dict(QUALITY_GATE))


def result_fixture(manifest, phase="confirmation", gains=5, losses=0):
    ids = [t["id"] for t in manifest["tasks"][phase]]
    gain_ids, loss_ids = set(ids[:gains]), set(ids[gains:gains+losses])
    rows = []
    for entry in make_schedule(manifest, phase):
        task_id, method = entry["task_id"], entry["method"]
        solved = (method == "adaptive_repair" if task_id in gain_ids else
                  method == "best_of_two" if task_id in loss_ids else True)
        rows.append(dict(entry, manifest_sha256=manifest_hash(manifest),
                         status="completed", valid=True, solved=solved, total_tokens=100))
    return rows


class V4ProtocolTests(unittest.TestCase):
    def test_frozen_integrity_and_exclusive_registration(self):
        manifest = manifest_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"manifest.json"
            digest = freeze_manifest(manifest, path)
            self.assertEqual(digest, manifest_hash(verify_manifest(path)))
            with self.assertRaises(FileExistsError):
                freeze_manifest(manifest, path)
            data = json.loads(path.read_text())
            data["manifest"]["prompts"]["initial"] = "changed"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "integrity"):
                verify_manifest(path)

    def test_disjoint_and_prior_exclusion_with_development_exception(self):
        manifest = manifest_fixture()
        manifest["previous_task_ids"].append("task-0")
        validate_manifest(manifest)
        for change in ("prior", "overlap", "duplicate"):
            broken = copy.deepcopy(manifest)
            if change == "prior":
                broken["previous_task_ids"].append("task-12")
            elif change == "overlap":
                broken["tasks"]["confirmation"][0] = broken["tasks"]["development"][0]
            else:
                broken["tasks"]["confirmation"][1] = broken["tasks"]["confirmation"][0]
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_manifest(broken)

    def test_schedule_is_deterministic_complete_and_bound_to_seed(self):
        manifest = manifest_fixture()
        schedule = make_schedule(manifest, "confirmation")
        self.assertEqual(len(schedule), 80)
        self.assertEqual(schedule, make_schedule(copy.deepcopy(manifest), "confirmation"))
        self.assertEqual({r["rep"] for r in schedule}, {0})
        manifest["schedule"] = {p: make_schedule(manifest, p) for p in manifest["tasks"]}
        validate_manifest(manifest)
        manifest["seed"] += 1
        with self.assertRaisesRegex(ValueError, "schedule"):
            validate_manifest(manifest)

    def test_complete_results_required_and_bound_to_manifest(self):
        manifest = manifest_fixture()
        rows = result_fixture(manifest)
        validate_results(manifest, "confirmation", rows)
        alterations = [rows[:-1], rows+[rows[0]]]
        for key, value in (("manifest_sha256", "x"*64), ("status", "transport_unknown"),
                           ("valid", False), ("solved", 1), ("rep", True), ("order", 999)):
            broken = copy.deepcopy(rows)
            broken[0][key] = value
            alterations.append(broken)
        for broken in alterations:
            with self.subTest(result=broken[0]), self.assertRaises(ValueError):
                validate_results(manifest, "confirmation", broken)
            report = evaluate_gates(manifest, "confirmation", broken, 0)
            self.assertFalse(report["quality_pass"])
            self.assertFalse(report["promotion_allowed"])

    def test_quality_threshold_requires_five_gains_with_zero_losses(self):
        manifest = manifest_fixture()
        for gains, losses, passes in ((0, 0, False), (2, 0, False), (4, 0, False),
                                      (5, 0, True), (8, 1, False)):
            report = evaluate_gates(manifest, "confirmation", result_fixture(manifest, gains=gains, losses=losses), 0)
            with self.subTest(gains=gains, losses=losses):
                self.assertEqual(report["quality_pass"], passes)
                self.assertEqual(report["losses"], losses)
                self.assertFalse(report["promotion_allowed"])
        self.assertEqual(evaluate_gates(manifest, "confirmation", result_fixture(manifest), 0)["sign_p"], 1/32)

    def test_token_gate_is_separate_unknown_fails_closed_and_shared_cost_counted(self):
        manifest = manifest_fixture()
        rows = result_fixture(manifest)
        report = evaluate_gates(manifest, "confirmation", rows)
        self.assertTrue(report["quality_pass"])
        self.assertFalse(report["token_deployment_pass"])
        for row in rows:
            if row["method"] == "adaptive_repair":
                row["total_tokens"] = 125
        self.assertFalse(evaluate_gates(manifest, "confirmation", rows, 0)["token_deployment_pass"])
        report = evaluate_gates(manifest, "confirmation", rows, 2000)
        self.assertEqual(report["token_ratio"], 1.2)
        self.assertTrue(report["token_deployment_pass"])
        rows[0]["total_tokens"] = None
        self.assertFalse(evaluate_gates(manifest, "confirmation", rows, 2000)["token_deployment_pass"])
        rows[0]["total_tokens"] = -1
        self.assertEqual(evaluate_gates(manifest, "confirmation", rows, 0)["verdict"], "INVALID_OR_INCOMPLETE")

    def test_pilot_and_development_cannot_claim_confirmation(self):
        for pilot in (False, True):
            manifest = manifest_fixture(pilot)
            rows = result_fixture(manifest, "development", gains=8)
            report = evaluate_gates(manifest, "development", rows, 0)
            self.assertEqual(report["verdict"], "DEVELOPMENT_ONLY")
            self.assertFalse(report["quality_pass"])
            self.assertFalse(report["eligible_for_replication"])
        manifest = manifest_fixture(True)
        self.assertFalse(evaluate_gates(manifest, "confirmation", [], 0)["quality_pass"])

    def test_cannot_silently_weaken_gate_or_shrink_confirmation(self):
        manifest = manifest_fixture()
        manifest["gates"]["maximum_regressions"] = 1
        with self.assertRaises(ValueError):
            validate_manifest(manifest)
        manifest = manifest_fixture()
        manifest["tasks"]["confirmation"].pop()
        with self.assertRaises(ValueError):
            validate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
