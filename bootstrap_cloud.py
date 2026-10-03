#!/usr/bin/env python3
from pathlib import Path
import base64, hashlib, lzma, zipfile

parts = [
    Path(f"cloud_bundle/ascendra.zip.xz.b64.part{i}").read_text().strip()
    for i in range(9)
]
xz = base64.b64decode("".join(parts))
expected_xz = "ee71c95fb9afeef479222b4a2eaa0117284c95675d43a2589cc260354024c3e0"
got_xz = hashlib.sha256(xz).hexdigest()
if got_xz != expected_xz:
    raise SystemExit(f"transport bundle sha256 mismatch: {got_xz}")

raw = lzma.decompress(xz)
expected_zip = "c81bc215b9ae5f43ebbe572a7e2f428bc91d30eb8d5c2b01208149e966463f61"
got_zip = hashlib.sha256(raw).hexdigest()
if got_zip != expected_zip:
    raise SystemExit(f"zip sha256 mismatch: {got_zip}")

Path("ASCENDRA_v0.3.1_CLOUD_READY.zip").write_bytes(raw)
with zipfile.ZipFile("ASCENDRA_v0.3.1_CLOUD_READY.zip") as z:
    z.extractall(".")
print("ASCENDRA cloud bundle restored", got_zip)
