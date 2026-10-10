"""Download and hash-check a pinned UK AISI OLMo artifact. Never run a model."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import time


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_header(path):
    # Header inspection reads metadata only; it does not load tensor contents.
    with path.open("rb") as stream:
        length_raw = stream.read(8)
        if len(length_raw) != 8:
            raise ValueError(f"Invalid safetensors file: {path.name}")
        header_length = struct.unpack("<Q", length_raw)[0]
        if header_length > 16 * 1024 * 1024:
            raise ValueError(f"Unexpected safetensors header: {path.name}")
        header = json.loads(stream.read(header_length))
    tensors = [value for name, value in header.items() if name != "__metadata__"]
    return {
        "tensor_count": len(tensors),
        "dtype_counts": dict(Counter(value["dtype"] for value in tensors)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--report-directory", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if plan.get("generation_authorized") or plan.get("training_authorized"):
        raise ValueError("This script accepts download-only plans.")
    destination = args.destination.resolve()
    reports = args.report_directory.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    # Public artifacts require no token. Disable implicit credential discovery.
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_HUB_DISABLE_XET"] = "0"
    os.environ["HF_XET_HIGH_PERFORMANCE"] = "1"
    os.environ["HF_XET_CHUNK_CACHE_SIZE_BYTES"] = "0"
    os.environ["HF_XET_SHARD_CACHE_SIZE_LIMIT"] = "536870912"
    os.environ["HF_XET_CACHE"] = str(destination / ".xet-cache")
    from huggingface_hub import hf_hub_download

    jobs = []
    for artifact in plan["artifacts"]:
        if len(artifact["revision"]) != 40:
            raise ValueError("A full pinned Hugging Face revision is required.")
        for record in artifact["files"]:
            name = Path(record["name"])
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("Invalid artifact filename.")
            path = destination / artifact["directory_name"] / name
            jobs.append((artifact, record, path))

    missing_bytes = sum(
        record["bytes"]
        for _, record, path in jobs
        if not path.exists() or path.stat().st_size != record["bytes"]
    )
    reserve = plan["minimum_free_bytes_after_download"]
    free = shutil.disk_usage(destination).free
    if free < missing_bytes + reserve:
        raise RuntimeError(
            f"Insufficient disk: {free / 1e9:.2f} GB free; "
            f"need {missing_bytes / 1e9:.2f} GB download plus {reserve / 1e9:.2f} GB reserve."
        )

    state = {
        "status": "downloading",
        "started_at": now(),
        "plan_sha256": sha256(args.plan),
        "download_bytes": plan["download_bytes"],
        "destination": str(destination),
        "model_loading_executed": False,
        "model_generation_executed": False,
        "training_executed": False,
        "completed_files": [],
    }
    write_json(reports / "download-status.json", state)
    started = time.monotonic()

    def fetch(job):
        artifact, record, path = job
        hf_hub_download(
            repo_id=artifact["model_id"],
            revision=artifact["revision"],
            filename=record["name"],
            local_dir=destination / artifact["directory_name"],
            token=False,
        )
        if path.stat().st_size != record["bytes"]:
            raise RuntimeError(f"File size mismatch: {record['name']}")
        digest = sha256(path)
        if digest != record["sha256"]:
            raise RuntimeError(f"SHA-256 mismatch: {record['name']}")
        result = {
            "role": artifact["role"],
            "model_id": artifact["model_id"],
            "revision": artifact["revision"],
            "name": record["name"],
            "bytes": path.stat().st_size,
            "sha256": digest,
            "verified": True,
        }
        if path.suffix == ".safetensors":
            result["safetensors_metadata"] = tensor_header(path)
            if set(result["safetensors_metadata"]["dtype_counts"]) != {
                artifact["expected_weight_dtype"]
            }:
                raise RuntimeError(f"Unexpected weight precision: {record['name']}")
        return result

    try:
        workers = min(2, max(1, plan["max_download_workers"]))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fetch, job) for job in jobs]
            for future in as_completed(futures):
                record = future.result()
                state["completed_files"].append(record)
                state["updated_at"] = now()
                write_json(reports / "download-status.json", state)
                print(f"Verified {record['role']}/{record['name']}", flush=True)

        base = next(item for item in plan["artifacts"] if item["role"] == "base")
        adapter = next(item for item in plan["artifacts"] if item["role"] == "adapter")
        config = json.loads((destination / adapter["directory_name"] / "adapter_config.json").read_text())
        if config["base_model_name_or_path"] != base["model_id"]:
            raise RuntimeError("Adapter base model does not match the pinned base.")
        state["adapter_base_identity_verified"] = True
        state["status"] = "verified_complete"
        state["finished_at"] = now()
        state["elapsed_seconds"] = round(time.monotonic() - started, 3)
        state["remaining_disk_bytes"] = shutil.disk_usage(destination).free
        write_json(reports / "download-verification.json", state)
        write_json(reports / "download-status.json", state)
        print("All pinned OLMo base and adapter files are downloaded and verified. No model was loaded or run.", flush=True)
    except BaseException as error:
        state["status"] = "failed"
        state["finished_at"] = now()
        state["error_type"] = type(error).__name__
        state["error"] = str(error)
        write_json(reports / "download-status.json", state)
        raise


if __name__ == "__main__":
    main()
