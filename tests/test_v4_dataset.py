import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ascendra import v4_dataset as dataset


class DatasetBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / ".ascendra/lcb-source/test6.jsonl"
        self.source.parent.mkdir(parents=True)
        self.row = {
            "question_id": "abc001_a", "question_content": "Public statement",
            "question_title": "Example", "platform": "atcoder", "difficulty": "medium",
            "public_test_cases": json.dumps([{"input": "1\n", "output": "1\n", "testtype": "stdin", "unexpected": "ignored"}]),
            "private_test_cases": json.dumps([{"input": "SECRET_INPUT", "output": "SECRET_OUTPUT", "testtype": "stdin"}]),
            "private_metadata": "SECRET_METADATA",
        }
        self.source.write_text(json.dumps(self.row) + "\n")
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.mock_sha = patch.object(dataset, "DATA_SHA", digest)
        self.mock_sha.start()
        self.addCleanup(self.mock_sha.stop)

    def test_catalogue_never_decodes_or_exposes_private_fields(self):
        with patch.object(dataset, "decode_private", side_effect=AssertionError("Must not decode")):
            catalog = dataset.load_public_catalog(self.root)
        text = json.dumps(catalog)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("unexpected", text)
        self.assertEqual(catalog[0]["task_id"], "abc001_a")

    def test_changed_source_rejected_before_decoding(self):
        self.source.write_text(self.source.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            dataset.load_public_catalog(self.root)

    def test_previous_includes_partial_and_invalidated_registrations(self):
        for name, obj in {
            "stopped": {"splits": {"development": ["abc001_a"], "confirmation": ["abc001_b"]}},
            "invalidated": {"schedule": [{"task": "abc002_a"}]},
            "current": {"task_ids": ["abc003_a"]},
        }.items():
            path = self.root / ".ascendra" / name
            path.mkdir()
            (path / "preregistration.json").write_text(json.dumps(obj))
        self.assertEqual(dataset.previous_task_ids(self.root), {"abc001_a", "abc001_b", "abc002_a", "abc003_a"})
        self.assertNotIn("abc003_a", dataset.previous_task_ids(self.root, exclude_study="current"))

    def test_materialization_private_boundary_and_resume_integrity(self):
        metadata = dataset.materialize_selected(self.root, "pilot", ["abc001_a"])
        self.assertNotIn("SECRET", json.dumps(metadata))
        study = self.root / ".ascendra/pilot"
        public = (study / metadata[0]["public_path"]).read_text()
        self.assertNotIn("SECRET", public)
        private_path = study / metadata[0]["private_path"]
        self.assertEqual(private_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(metadata, dataset.materialize_selected(self.root, "pilot", ["abc001_a"]))
        private_path.write_text("tampered")
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            dataset.materialize_selected(self.root, "pilot", ["abc001_a"])

    def test_v4_partial_manifest_reserves_confirmation_ids(self):
        study = self.root / ".ascendra/partial-v4"
        study.mkdir()
        envelope = {"manifest": {"id": "not-a-task", "tasks": {
            "development": [{"id": "abc001_a"}],
            "confirmation": [{"id": "abc002_b"}],
        }}, "sha256": "fixture"}
        (study / "manifest.json").write_text(json.dumps(envelope))
        self.assertEqual(dataset.previous_task_ids(self.root), {"abc001_a", "abc002_b"})
        self.assertEqual(dataset.previous_task_ids(self.root, exclude_study="partial-v4"), set())

    def test_unknown_duplicate_and_traversal_ids_are_rejected(self):
        for ids in (["missing"], ["abc001_a", "abc001_a"], ["../outside"], []):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                dataset.materialize_selected(self.root, "pilot", ids)
        with self.assertRaisesRegex(ValueError, "dedicated directory"):
            dataset.materialize_selected(self.root, self.root / "outside", ["abc001_a"])

    def test_bad_private_format_never_publishes_partial_tasks(self):
        with patch.object(dataset, "decode_private", return_value=[{"input": "x", "output": 1, "testtype": "stdin"}]):
            with self.assertRaisesRegex(ValueError, "Unsupported private"):
                dataset.materialize_selected(self.root, "pilot", ["abc001_a"])
        self.assertFalse((self.root / ".ascendra/pilot/tasks").exists())
        self.assertFalse(list((self.root / ".ascendra/pilot").glob(".tasks-building-*")))

    def test_already_registered_study_is_not_modified(self):
        study = self.root / ".ascendra/old"
        study.mkdir()
        (study / "preregistration.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "already registered"):
            dataset.materialize_selected(self.root, "old", ["abc001_a"])


if __name__ == "__main__":
    unittest.main()
