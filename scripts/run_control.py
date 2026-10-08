"""Prepare or explicitly launch control episodes using the official harness."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "vendor/Instrumental-Choices"
TASKS = ["ledger_audit", "budget_siphon", "quota_boost", "deployment_guardian",
         "training_preserver", "final_instance", "memory_keeper"]


def main() -> int:
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument("--config", type=Path, default=ROOT / "config/control.json")
    config_args, _ = config_parser.parse_known_args()
    CONFIG = json.loads(config_args.config.read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=config_args.config)
    parser.add_argument("--tasks", nargs="+", choices=TASKS,
                        default=[CONFIG["default_debug_task"]])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--variants", nargs="+", choices=CONFIG["variants"],
                        default=CONFIG["variants"],
                        help="Select variants explicitly, e.g. variant A alone.")
    parser.add_argument("--seed", type=int, default=100000)
    parser.add_argument("--prompt-ablation", choices=["remove_sandbox_sentence"],
                        help="Run a separately labelled diagnostic with one system-prompt sentence removed.")
    parser.add_argument("--execute", action="store_true",
                        help="Actually launch episodes. Without this flag, print the plan only.")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.prompt_ablation and args.tasks != ["budget_siphon"]:
        parser.error("The sandbox-sentence diagnostic is supported only for budget_siphon")
    config = dict(CONFIG)
    config.update(tasks=args.tasks, variants=args.variants, repeats=args.repeats,
                  planned_episodes=len(args.tasks) * len(args.variants) * args.repeats,
                  seed_schedule="seed + repeat_index * 100 + task_index * 2 + variant_index",
                  initial_seed=args.seed, message_limit=160, working_limit_seconds=1800,
                  log_model_api=True)
    if args.prompt_ablation:
        config.update(prompt_ablation=args.prompt_ablation, official_prompt_unmodified=False,
                      ablation_task_file="scripts/budget_siphon_no_sandbox_task.py")
    print(json.dumps(config, indent=2))
    if not args.execute:
        print("Plan only. No model requests, containers, or benchmark episodes launched.")
        return 0

    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=BENCH, text=True).strip()
    if revision != CONFIG["benchmark_revision"]:
        raise RuntimeError("Benchmark revision differs from the pinned setup")
    base_url = os.environ.get("CONTROL_BASE_URL", "http://127.0.0.1:18000/v1")
    if not base_url.startswith("http://127.0.0.1:"):
        raise RuntimeError("Expected the local SSH tunnel endpoint")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "logs" / f"control_{stamp}"
    output.mkdir(parents=True)
    (output / "control_config.json").write_text(json.dumps(config, indent=2) + "\n")
    env = dict(os.environ, PYTHONPATH=str(BENCH),
               CONTROL_API_KEY="local-ssh-only", CONTROL_BASE_URL=base_url)
    inspect = str(BENCH / ".venv/bin/inspect")
    python = str(BENCH / ".venv/bin/python")
    model = "openai-api/control/" + CONFIG["served_model_name"]
    manifest = [python, "scripts/write_run_manifest.py", "--output",
                str(output / "run_manifest.json"), "--repo-root", str(BENCH),
                "--log-root", str(output), "--repeats", str(args.repeats),
                "--variant-profile", "benchmark", "--models", model,
                "--tasks", *args.tasks, "--tool-trace-audit-enabled", "false",
                "--command", " ".join(sys.argv)]
    for task in args.tasks:
        compose = ("sandboxes/aio-anvil-compose.yaml" if task == "ledger_audit"
                   else "inspect_ic/tasks/final_instance/compose.aio.yaml" if task == "final_instance"
                   else "sandboxes/aio-compose.yaml")
        manifest.extend(["--compose", f"{task}={compose}"])
    subprocess.run([*manifest, "--status", "started"], cwd=BENCH, env=env, check=True)
    try:
        for repeat_index in range(args.repeats):
            for task_index, task in enumerate(args.tasks):
                for variant_index, variant in enumerate(args.variants):
                    seed = args.seed + repeat_index * 100 + task_index * 2 + variant_index
                    episode_dir = output / f"repeat_{repeat_index + 1:02}" / task / variant
                    task_file = (os.path.relpath(ROOT / "scripts/budget_siphon_no_sandbox_task.py", BENCH)
                                 if args.prompt_ablation
                                 else f"inspect_ic/tasks/{task}/task_{task}.py")
                    command = [inspect, "eval", task_file,
                               "--model", model, "--model-base-url", base_url,
                               "-M", "responses_api=false", "-M", "strict_tools=false",
                               "-T", "variant_profile=benchmark", "-T", f"variant_id={variant}",
                               "--temperature", str(CONFIG["temperature"]),
                               "--top-p", str(CONFIG["top_p"]),
                               "--max-tokens", str(CONFIG["max_tokens_per_response"]),
                               "--seed", str(seed), "--max-samples", "1",
                               "--limit", "1",
                               "--max-subprocesses", "1", "--max-connections", "1",
                               "--max-retries", "2", "--timeout", "180",
                               "--display", "plain",
                               "--message-limit", "160", "--working-limit", "1800",
                               "--log-model-api",
                               "--log-format", "eval", "--log-dir", str(episode_dir)]
                    subprocess.run(command, cwd=BENCH, env=env, check=True)
        subprocess.run([python, "scripts/analyze_tool_traces.py", str(output),
                        "--output-dir", str(output / "tool_analysis")],
                       cwd=BENCH, env=env, check=True)
        subprocess.run([python, "scripts/render_tool_trace_report.py",
                        str(output / "tool_analysis")], cwd=BENCH, env=env, check=True)
    except BaseException:
        subprocess.run([*manifest, "--status", "failed", "--exit-code", "1"],
                       cwd=BENCH, env=env, check=False)
        raise
    subprocess.run([*manifest, "--status", "completed", "--exit-code", "0"],
                   cwd=BENCH, env=env, check=True)
    print(f"Control run saved to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
