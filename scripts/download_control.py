"""Download the pinned checkpoint. Never load weights or generate text."""
import json
from pathlib import Path
from huggingface_hub import snapshot_download

root = Path(__file__).resolve().parents[1]
config = json.loads((root / "config/control.json").read_text())
destination = root / "models/qwen-control"
snapshot_download(
    repo_id=config["model_id"],
    revision=config["revision"],
    local_dir=destination,
    allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja"],
    max_workers=4,
)
print(f"Pinned control checkpoint downloaded to {destination}")
