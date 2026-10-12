"""Serve the pinned BF16 Qwen3.5-9B control in a bounded personal Vast session."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from cloud_gpu_trial import CONFIG, OUT, PLAN, PLAN_PATH, ROOT, guard, stop, write


def prepare():
    assert PLAN["spend_authorized"] and not CONFIG["adapter_enabled"] and CONFIG["quantization"] is None
    pinned = json.loads((ROOT / PLAN["checkpoint_files_plan"]).read_text())
    records = []
    for artifact in pinned["artifacts"]:
        assert artifact["role"] == "base" and artifact["revision"] == CONFIG["revision"]
        for record in artifact["files"]:
            path = ROOT / "models" / artifact["directory_name"] / record["name"]
            with path.open("rb") as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            assert path.stat().st_size == record["bytes"] and digest == record["sha256"]
            records.append(dict(record, verified=True))
    write("checkpoint-verification.json", {"files": records, "model_id": CONFIG["model_id"],
        "revision": CONFIG["revision"], "adapter_enabled": False, "model_generation_requests": 0})
    subprocess.run([sys.executable, str(ROOT / "scripts/check_qwen35_tool_parser.py")], check=True)


def supervise():
    assert not CONFIG["adapter_enabled"] and CONFIG["quantization"] is None
    if (OUT / "server-process.json").exists():
        raise RuntimeError("Refusing duplicate inference server.")
    session = json.loads((OUT / "session.json").read_text())
    env = dict(os.environ, HF_HUB_OFFLINE="1", DO_NOT_TRACK="1", VLLM_NO_USAGE_STATS="1",
        QWEN35_RAW_GENERATIONS_LOG=str(OUT / "raw-model-outputs.jsonl"))
    defaults = {k: CONFIG[k] for k in ("top_k", "min_p", "repetition_penalty", "presence_penalty")}
    cmd = [str(ROOT / "inference/qwen35/.venv/bin/vllm"), "serve", str(ROOT / CONFIG["model_directory"]),
        "--served-model-name", CONFIG["served_model_name"], "--host", "127.0.0.1", "--port", "8000",
        "--dtype", "bfloat16", "--max-model-len", str(CONFIG["max_model_len"]), "--max-num-seqs", "1",
        "--max-num-batched-tokens", "2048", "--tensor-parallel-size", "1", "--gpu-memory-utilization", "0.95",
        "--language-model-only", "--enforce-eager", "--chat-template", str(ROOT / CONFIG["native_chat_template"]),
        "--default-chat-template-kwargs", '{"enable_thinking":true}', "--reasoning-parser", "qwen3",
        "--enable-auto-tool-choice", "--tool-call-parser", "qwen35_audited",
        "--tool-parser-plugin", str(ROOT / "scripts/qwen35_tool_parser_audit.py"),
        "--generation-config", "vllm", "--override-generation-config", json.dumps(defaults),
        "--api-key", "local-ssh-only"]
    write("server-command.json", cmd)
    with (OUT / "server.log").open("w") as log:
        process = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        write("server-process.json", {"pid": process.pid})
        while time.time() < session["deadline_epoch"]:
            if process.poll() is not None:
                write("server-exit.json", {"exit_code": process.returncode})
                return
            time.sleep(10)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["prepare", "supervise", "launch", "guard", "stop"])
    action = p.parse_args().action
    if action == "stop":
        stop("Qwen3.5 control screen complete or failed; retain workspace pending deletion authorization")
        return
    assert PLAN["spend_authorized"] and PLAN.get("rented_at")
    if action == "guard":
        guard()
    elif action == "prepare":
        prepare()
    elif action == "supervise":
        supervise()
    else:
        with (OUT / "supervisor.log").open("w") as log:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "supervise"], cwd=ROOT,
                env=dict(os.environ, CLOUD_TRIAL_PLAN=PLAN_PATH), stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        print("Bounded Qwen3.5 inference supervisor started.")


if __name__ == "__main__":
    main()
