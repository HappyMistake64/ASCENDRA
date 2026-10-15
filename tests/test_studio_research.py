import io
import json
import socket
import time
import unittest
from email.message import Message
from unittest.mock import Mock, patch

from ascendra import studio_research as r


PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


class Response(io.BytesIO):
    status = 200

    def __init__(self, data, kind="text/html", length=None):
        super().__init__(data)
        self.headers = Message()
        self.headers["Content-Type"] = kind
        if length is not None:
            self.headers["Content-Length"] = str(length)


class ResearchTests(unittest.TestCase):
    def test_explicit_docs_extract_text_and_provenance(self):
        with patch.object(r, "_fetch", return_value=(
                "<title>Docs</title><script>ignore me</script><h1>Public evidence</h1>", "text/html")):
            report = r.research("testing", urls=["https://example.org/docs"])
        self.assertEqual(report["status"], "complete")
        source = report["sources"][0]
        self.assertEqual(source["title"], "Docs")
        self.assertNotIn("ignore me", source["excerpt"])
        self.assertIn("+00:00", source["retrieved_at"])
        self.assertLessEqual(source["retrieved_at"], report["researched_at"])
        self.assertIn("Untrusted", report["evidence_policy"])

    def test_real_discovery_protocol_then_source_fetch(self):
        payload = json.dumps(["testing", ["Testing"], [""], ["https://en.wikipedia.org/wiki/Testing"]])
        with patch.object(r, "_fetch", side_effect=[(payload, "application/json"), ("Evidence", "text/plain")]) as fetch:
            report = r.research("testing", limit=1)
        self.assertEqual(report["status"], "complete")
        self.assertIn("action=opensearch", fetch.call_args_list[0].args[0])
        self.assertEqual(len(report["sources"]), 1)

    def test_discovery_failure_is_blocked_without_fake_sources(self):
        with patch.object(r, "_fetch", side_effect=OSError("secret-error")):
            report = r.research("testing")
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["sources"], [])
        self.assertNotIn("secret-error", str(report))

    def test_empty_discovery_is_blocked(self):
        with patch.object(r, "_fetch", return_value=('["x", [], [], []]', "application/json")):
            self.assertEqual(r.research("x")["status"], "blocked")

    def test_invalid_discovery_is_blocked(self):
        with patch.object(r, "_fetch", return_value=('{}', "application/json")):
            self.assertEqual(r.research("x")["status"], "blocked")

    def test_duplicates_and_limit(self):
        with patch.object(r, "_fetch", return_value=("Evidence", "text/plain")) as fetch:
            result = r.research("x", urls=["https://example.org/a"] * 3 + ["https://example.org/b"], limit=1)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(len(result["sources"]), 1)

    def test_invalid_inputs(self):
        for kwargs in ({"topic": ""}, {"topic": "x", "limit": 0}, {"topic": "x", "limit": True},
                       {"topic": "x", "limit": 9}, {"topic": "x", "urls": ["x"] * 9}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                r.research(**kwargs)

    def test_url_validation(self):
        for url in ("http://example.org", "file:///etc/passwd", "https://u:p@example.org",
                    "https://example.org:8443", "https://example.org/#fragment",
                    "https://example.org/\n", "https://example.org\\@localhost", "https://[::1%25lo0]/"):
            with self.subTest(url=url), self.assertRaises(r.ResearchBlocked):
                r._validate_url(url)

    def test_private_dns_and_mixed_addresses_rejected(self):
        for ip in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "100.64.0.1"):
            private = (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
            with self.subTest(ip=ip), patch.object(r.socket, "getaddrinfo", return_value=PUBLIC + [private]):
                with self.assertRaises(r.ResearchBlocked):
                    r._validate_url("https://example.org")

    def test_public_url_and_redirect_rejection(self):
        with patch.object(r.socket, "getaddrinfo", return_value=PUBLIC):
            self.assertEqual(r._validate_url("https://example.org/docs").hostname, "example.org")
        with self.assertRaises(r.ResearchBlocked):
            r._NoRedirect().redirect_request(None, None, 302, "", {}, "https://127.0.0.1")

    def test_fetch_bounds_content_and_size(self):
        cases = [Response(b"x", kind="application/octet-stream"),
                 Response(b"x", length=r.MAX_BYTES + 1),
                 Response(b"x" * (r.MAX_BYTES + 1))]
        for response in cases:
            opener = Mock()
            opener.open.return_value = response
            with patch.object(r.socket, "getaddrinfo", return_value=PUBLIC), \
                    patch.object(r.urllib.request, "build_opener", return_value=opener), \
                    self.assertRaises(r.ResearchBlocked):
                r._fetch("https://example.org", time.monotonic() + 10)

    def test_fetch_timeout_and_encoding(self):
        with patch.object(r.socket, "getaddrinfo", return_value=PUBLIC), self.assertRaises(r.ResearchBlocked):
            r._fetch("https://example.org", time.monotonic() - 1)
        response = Response(b"text")
        response.headers["Content-Encoding"] = "gzip"
        opener = Mock()
        opener.open.return_value = response
        with patch.object(r.socket, "getaddrinfo", return_value=PUBLIC), \
                patch.object(r.urllib.request, "build_opener", return_value=opener), \
                self.assertRaises(r.ResearchBlocked):
            r._fetch("https://example.org", time.monotonic() + 10)

    def test_fetch_success(self):
        opener = Mock()
        opener.open.return_value = Response(b"Documentation", "text/plain")
        with patch.object(r.socket, "getaddrinfo", return_value=PUBLIC), \
                patch.object(r.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(r._fetch("https://example.org", time.monotonic() + 10),
                             ("Documentation", "text/plain"))

    def test_partial_success_discloses_failure(self):
        with patch.object(r, "_fetch", side_effect=[OSError(), ("Evidence", "text/plain")]):
            result = r.research("x", urls=["https://example.org/a", "https://example.org/b"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
