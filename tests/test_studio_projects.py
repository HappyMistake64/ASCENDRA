import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ascendra.studio_projects import build_project, MAX_FILE_BYTES


def document(body="", head=""):
    return '<!doctype html><html><head>' + head + '</head><body>' + body + '</body></html>'


def answer(html=None, extras=()):
    return {"files": [{"path": "index.html", "content": html or document("Hello")}, *extras]}


class ProjectBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / "app"

    def build(self, response):
        return build_project("A useful counter", self.destination, decide=lambda request, schema: response)

    def test_build_has_host_manifest_readme_and_honest_checks(self):
        response = answer(document('<script src="./app.js"></script>', '<link href="styles.css" rel="stylesheet">'), [
            {"path": "app.js", "content": "document.title = 'Counter';"},
            {"path": "styles.css", "content": "body {color: green}"}])
        report = self.build(response)
        self.assertEqual(report["status"], "built")
        self.assertFalse(report["checks"]["code_executed"])
        self.assertIsNone(report["checks"]["functional_tests_passed"])
        self.assertEqual(json.loads((self.destination / "ascendra-project.json").read_text()), report)
        for entry in report["files"]:
            self.assertEqual(hashlib.sha256((self.destination / entry["path"]).read_bytes()).hexdigest(), entry["sha256"])
        self.assertIn("python -m http.server", (self.destination / "README.md").read_text())

    def test_existing_destination_not_touched_or_sent_to_model(self):
        self.destination.mkdir()
        (self.destination / "keep").write_text("keep")
        with self.assertRaises(FileExistsError):
            build_project("Counter", self.destination, decide=lambda *args: self.fail("model called"))
        self.assertEqual((self.destination / "keep").read_text(), "keep")

    def test_destination_created_during_model_call_not_overwritten(self):
        def decide(*args):
            self.destination.mkdir()
            return answer()
        with self.assertRaises(FileExistsError):
            build_project("Counter", self.destination, decide=decide)
        self.assertTrue(self.destination.is_dir())
        self.assertFalse(list(self.root.glob(".ascendra-build-*")))

    def test_invalid_generated_paths(self):
        for path in ("../escape", "/tmp/x", ".env", ".git/config", "assets/extra.js", "README.md", "ascendra-project.json", "index.HTML"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.build({"files": [{"path": path, "content": "bad"}]})
            self.assertFalse(self.destination.exists())

    def test_malformed_output(self):
        for response in (None, {}, {"files": []}, {"files": "bad"}, {"files": [{"path": "index.html", "content": 2}]},
                         {**answer(), "passed": True}, answer(extras=[{"path": "index.html", "content": document()}])):
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.build(response)
        self.assertFalse(self.destination.exists())

    def test_bounds_count_bytes_and_nul(self):
        for response in (answer(document("é" * (MAX_FILE_BYTES // 2))), answer(document("\0")),
                         {"files": answer()["files"] * 4}, {"files": [{"path": "app.js", "content": "hello"}]}):
            with self.assertRaises(ValueError):
                self.build(response)

    def test_bad_local_references_and_schemes(self):
        for reference in ("missing.css", "../index.html", "%2e%2e/index.html", "/index.html", "..\\index.html", "%252e%252e/index.html", "javascript:alert(1)", "file:///etc/passwd", "//example.org/a"):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                self.build(answer(document(head='<link href="' + reference + '">')))

    def test_css_and_js_references_checked(self):
        for path, content in (("styles.css", "body{background:url(missing.png)}"),
                              ("styles.css", '@import "missing.css";'),
                              ("app.js", 'import "./missing.js";'),
                              ("app.js", 'import("../bad.js");')):
            with self.assertRaises(ValueError):
                self.build(answer(extras=[{"path": path, "content": content}]))

    def test_external_reference_reported_not_fetched(self):
        report = self.build(answer(document('<a href="https://example.org/">Docs</a>')))
        self.assertEqual(report["external_references"], ["https://example.org/"])

    def test_unsupported_html_constructs(self):
        for html in ("plain text", document('<iframe srcdoc="x"></iframe>'), document('<img srcset="x 2x">'),
                     document(head='<base href="https://example.org/">'), document(head='<style>body{background:url(missing.png)}</style>')):
            with self.assertRaises(ValueError):
                self.build(answer(html))

    def test_symlinks_rejected(self):
        self.destination.symlink_to(self.root / "missing")
        with self.assertRaises(ValueError):
            self.build(answer())
        link = self.root / "linked"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            build_project("Counter", link / "new", decide=lambda *args: answer())

    def test_invalid_description_or_missing_parent(self):
        for description in (None, "", "  ", "x" * 16001):
            with self.assertRaises(ValueError):
                build_project(description, self.destination, decide=lambda *args: answer())
        with self.assertRaises(ValueError):
            build_project("Counter", self.root / "missing" / "new", decide=lambda *args: answer())

    def test_publication_failure_cleans_staging(self):
        with patch("ascendra.studio_projects._rename_new", side_effect=OSError("failed")), self.assertRaises(OSError):
            self.build(answer())
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
