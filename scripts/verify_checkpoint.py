"""Verify downloaded file sizes, hashes and tensor headers without loading weights."""
import hashlib
import json
from pathlib import Path
import struct

root = Path(__file__).resolve().parents[1]
files = json.loads((root / "config/checkpoint_files.json").read_text())
report = []
for item in files:
    path = root / "models/qwen-control" / item["path"]
    assert path.stat().st_size == item["size"], f"Wrong file size: {path.name}"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    assert digest.hexdigest() == item["sha256"], f"Hash mismatch: {path.name}"
    with path.open("rb") as handle:
        header_size = struct.unpack("<Q", handle.read(8))[0]
        header = json.loads(handle.read(header_size))
    dtypes = sorted({v["dtype"] for k, v in header.items() if k != "__metadata__"})
    report.append({"path": path.name, "sha256": digest.hexdigest(),
                   "size": path.stat().st_size, "tensor_dtypes": dtypes})
    print(f"Verified {path.name}: SHA-256 matches, tensor types {dtypes}")
(root / "checkpoint-verification.json").write_text(json.dumps(report, indent=2) + "\n")
tokenizer_config = root / "models/qwen-control/tokenizer_config.json"
tokenizer = json.loads(tokenizer_config.read_text())
assert tokenizer.get("chat_template"), "No tokenizer chat template"
metadata = {
    "tokenizer_config_sha256": hashlib.sha256(tokenizer_config.read_bytes()).hexdigest(),
    "chat_template_sha256": hashlib.sha256(tokenizer["chat_template"].encode()).hexdigest(),
    "adapter_enabled": False,
    "weights_loaded": False,
    "model_generation_executed": False,
}
(root / "tokenizer-verification.json").write_text(json.dumps(metadata, indent=2) + "\n")
print("Tokenizer and chat-template fingerprints saved; no weights loaded.")
