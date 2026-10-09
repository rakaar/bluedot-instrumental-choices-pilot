"""Download the pinned checkpoint. Never load weights or generate text."""
import argparse
import json
from pathlib import Path
from huggingface_hub import snapshot_download

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', type=Path, default=root / 'config/control.json')
args = parser.parse_args()
config = json.loads(args.config.read_text())
destination = root / config.get('model_directory', 'models/qwen-control')
snapshot_download(
    repo_id=config["model_id"],
    revision=config["revision"],
    local_dir=destination,
    allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja"],
    max_workers=4,
)
print(f"Pinned control checkpoint downloaded to {destination}")
