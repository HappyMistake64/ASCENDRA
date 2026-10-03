#!/usr/bin/env python3
from pathlib import Path
import base64,hashlib,zipfile
parts=[]
for i in range(4): parts.append(Path(f"cloud_bundle/ascendra.zip.b64.part{i}").read_text().strip())
raw=base64.b64decode("".join(parts))
expected="c81bc215b9ae5f43ebbe572a7e2f428bc91d30eb8d5c2b01208149e966463f61"
got=hashlib.sha256(raw).hexdigest()
if got!=expected: raise SystemExit(f"bundle sha256 mismatch: {got}")
Path("ASCENDRA_v0.3.1_CLOUD_READY.zip").write_bytes(raw)
with zipfile.ZipFile("ASCENDRA_v0.3.1_CLOUD_READY.zip") as z: z.extractall(".")
print("ASCENDRA cloud bundle restored", got)
