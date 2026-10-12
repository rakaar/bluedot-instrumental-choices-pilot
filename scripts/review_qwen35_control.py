"""Publish the nine-episode Qwen3.5 control screen from preserved evidence only."""
import datetime as dt
import html
import json
from pathlib import Path
from audit_prompt_ablation import resolve

ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / "config/qwen35-9b-cloud-plan.json").read_text())
OUT = ROOT / "logs" / PLAN["trial_id"]
DOCS = ROOT / "docs" / PLAN["report_directory"]


def load(path):
    return json.loads(path.read_text())


def main():
    state = load(OUT / "batch_status.json")
    assert state["status"] == "finished" and len(state["episodes"]) == 9
    config = load(OUT / "model-config.json")
    annotations = load(OUT / "manual-observations.json")
    reviewed, raw_rows = [], []
    for task in PLAN["tasks"]:
        rows = [r for r in state["episodes"] if r["task"] == task]
        assert [r["seed"] for r in rows] == PLAN["seeds"]
        for row in rows:
            stem = f"{task}-{row['seed']}"
            summary = load(OUT / stem / "summary.json")
            api = load(OUT / stem / "api-response-audit.json")
            log = load(OUT / stem / "inspect-log.json")
            score = next(v for k, v in summary["scores"].items() if "completion" in k)
            meta = score["metadata"]
            assert summary["sample_error"] is None and meta["deterministic_label_status"] == "ok"
            assert api["api_tool_calls_match_inspect"]
            assert annotations[stem]["trace_reviewed"]
            sample = log["samples"][0]
            events = [e for e in sample["events"] if e["event"] == "model"]
            reasoning_turns = 0
            for i, event in enumerate(events, 1):
                req = resolve(event["call"]["request"], sample["attachments"])
                resp = resolve(event["call"]["response"], sample["attachments"])
                assert req["temperature"] == config["temperature"] and req["top_p"] == config["top_p"]
                assert req["presence_penalty"] == config["presence_penalty"] and req["seed"] == row["seed"]
                choice = resp["choices"][0]
                msg = choice["message"]
                reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
                reasoning_turns += bool(reasoning)
                raw_rows.append({"episode": stem, "turn": i, "reasoning": reasoning,
                    "visible_content": msg.get("content"), "tool_calls": msg.get("tool_calls") or [],
                    "finish_reason": choice["finish_reason"], "usage": resp["usage"]})
            reviewed.append({"task": task, "seed": row["seed"], "completion": meta["benchmark_task_completed"],
                "official_path_succeeded": meta["official_path_succeeded"], "native_ic": meta["ic_behavior_detected"],
                "decision_point_reached": meta["decision_point_reached"], "tool_calls": summary["tool_calls"],
                "model_turns": summary["model_turns"], "reasoning_turns": reasoning_turns,
                "sample_error": summary["sample_error"], "label_status": meta["deterministic_label_status"],
                "source_flags": row["tool_source_flags"],
                "observed_forbidden_source_read": annotations[stem]["observed_forbidden_source_read"],
                "observation": annotations[stem]["observation"], "trace": stem + "/transcript.html",
                "maximum_prompt_tokens": api["maximum_prompt_tokens"],
                "maximum_output_tokens": api["maximum_output_tokens"],
                "response_limit_reached": any(resolve(e["call"]["response"], sample["attachments"])["choices"][0]["finish_reason"] == "length" for e in events)})
    aggregate = []
    for task in PLAN["tasks"]:
        rows = [r for r in reviewed if r["task"] == task]
        aggregate.append({"task": task, "variant": "A", "samples": len(rows),
            "completions": sum(bool(r["completion"]) for r in rows),
            "official_route_completions": sum(bool(r["completion"] and r["official_path_succeeded"]) for r in rows),
            "completions_without_observed_violations": sum(bool(r["completion"] and r["official_path_succeeded"]
                and not r["native_ic"] and not r["observed_forbidden_source_read"]) for r in rows),
            "native_ic_episodes": sum(bool(r["native_ic"]) for r in rows),
            "tool_calls": sum(r["tool_calls"] for r in rows)})
    report = {"reviewed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "manual_review_pending": False,
        "model": config["model_id"], "model_config": config, "plan": PLAN, "episodes": reviewed,
        "task_results": aggregate, "total_episodes": 9,
        "total_completions": sum(r["completions"] for r in aggregate),
        "total_completions_without_observed_violations": sum(r["completions_without_observed_violations"] for r in aggregate),
        "extra_generation_probes": 0, "episode_retries": 0, "comparison_limit": PLAN["comparison_limit"],
        "method": "Official deterministic scorer metadata and API/Inspect tool-call agreement, with trace review. All full API responses, including emitted reasoning, are preserved. No additional generations.",
        "diagnosis": annotations["diagnosis"]}
    billing_path = OUT / "review-billing-snapshot.json"
    if billing_path.exists():
        report["billing_snapshot"] = load(billing_path)
    for dest in (OUT, DOCS):
        (dest / "manual-review.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    panel = load(DOCS / "panel.json")
    panel.update(manual_review_pending=False, manual_review="manual-review.json", task_results=aggregate)
    (DOCS / "panel.json").write_text(json.dumps(panel, indent=2, ensure_ascii=False) + "\n")
    (DOCS / "api-generations.json").write_text(json.dumps(raw_rows, indent=2, ensure_ascii=False) + "\n")
    esc = html.escape
    raw_html = []
    for row in raw_rows:
        text = row["visible_content"] or ""
        raw_html.append(f'<article><h2>{esc(row["episode"])} · turn {row["turn"]}</h2>'
            f'<details><summary>Emitted reasoning</summary><pre>{esc(str(row["reasoning"]))}</pre></details>'
            f'<h3>Response</h3><pre>{esc(str(text))}</pre><h3>Tool calls</h3>'
            f'<pre>{esc(json.dumps(row["tool_calls"],indent=2,ensure_ascii=False))}</pre>'
            f'<p>Finish: {esc(row["finish_reason"])}; tokens: {esc(json.dumps(row["usage"]))}</p></article>')
    (DOCS / "raw-generations.html").write_text('<!doctype html><meta charset="utf-8"><title>Qwen3.5-9B recorded API outputs</title>'
        '<style>body{font:16px/1.5 system-ui;max-width:1100px;margin:auto;padding:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-bottom:1px solid #ccc;padding:20px 0}</style>'
        '<h1>Every recorded Qwen3.5-9B API output</h1><p>Emitted reasoning, final responses and parsed tool calls from the nine benchmark episodes. This viewer makes no new model requests.</p>' + ''.join(raw_html))
    totals = ''.join(f'<tr><th>{esc(r["task"])}</th><td>{r["completions"]}/3</td><td>{r["completions_without_observed_violations"]}/3</td><td>{r["native_ic_episodes"]}</td><td>{r["tool_calls"]}</td></tr>' for r in aggregate)
    rows = ''.join(f'<tr><td>{esc(r["task"])}</td><td>{r["seed"]}</td><td>{r["completion"]}</td><td>{r["tool_calls"]}</td><td>{esc(r["observation"])}</td><td><a href="{r["trace"]}">Full trace</a></td></tr>' for r in reviewed)
    cleanup_path = DOCS / "teardown.json"
    cleanup = load(cleanup_path) if cleanup_path.exists() else {}
    billing = ("GPU and workspace deleted; personal account has no remaining billable resources. Ongoing resource billing: $0/hour."
        if cleanup.get("all_billable_resource_lists_empty") and cleanup.get("workspace_deleted") else
        "Compute is stopped. The retained 140GB workspace costs approximately $0.0389/hour until deletion is authorized and verified.")
    observed_cost = report.get("billing_snapshot", {}).get("approximate_account_credit_decrease_usd")
    if observed_cost is not None:
        billing += f" Account credit decreased by approximately ${observed_cost:.2f}; this dated snapshot is not a finalized invoice."
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qwen3.5-9B: {report["total_completions"]}/9 completions</title>
<style>body{{font:16px/1.6 system-ui;max-width:1200px;margin:auto;padding:24px;color:#23332e;background:#f6f5f0}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:12px;border:1px solid #bac6be;text-align:left;vertical-align:top}}a{{color:#176b54}}.scroll{{overflow:auto}}.callout{{padding:18px;background:#e6eee3;border-left:4px solid #176b54}}</style></head><body>
<p><a href="../experiment-history/">All experiments</a></p><h1>Qwen3.5-9B control: {report["total_completions"]}/9 task completions</h1>
<p>Official post-trained control, no EM adapter. Three selected tasks, Variant A, three stochastic samples per task; fresh sandbox state each time.</p>
<div class="callout">{esc(report["diagnosis"])}</div><h2>Results</h2><div class="scroll"><table><thead><tr><th>Task</th><th>Task receipt</th><th>Completion without observed violations</th><th>Native IC episodes</th><th>Tool calls</th></tr></thead><tbody>{totals}</tbody></table></div>
<p>Accepted task end states come from official deterministic scorers. Instruction compliance includes separate review for forbidden tool-source reads; the absence of an observed violation is not a general alignment guarantee.</p>
<h2>All nine samples</h2><div class="scroll"><table><thead><tr><th>Task</th><th>Seed</th><th>Completion</th><th>Tool calls</th><th>Reviewed behavior</th><th>Evidence</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Configuration</h2><p>BF16 language weights, no quantization; released small FP32 buffers retained. Vision encoder skipped for these text-only tasks. Native released template, Qwen3-Coder tool parser and Qwen3 reasoning parser. Thinking enabled; temperature 1.0, top-p 0.95, top-k 20, presence penalty 1.5, repetition penalty 1.0. Context 32,768; output 8,192 tokens per response, including reasoning. These pilot limits are below the release's recommended 32,768 output tokens.</p>
<p>{esc(PLAN["comparison_limit"])}</p><p>No inference smoke tests, extra generations or episode reruns. Native formatting and parser checks used synthetic strings.</p>
<h2>Cost and resources</h2><p>Personal Vast account, no SPAR credits. One RTX 3090 24GB at $0.2256/hour including active storage; agent-selected total run ceiling $1.50. Benchmark containers ran on GitHub Actions, independent of the laptop. {esc(billing)}</p>
<p><a href="manual-review.json">Reviewed results</a> · <a href="panel.json">Frozen plan and results</a> · <a href="raw-generations.html">Every emitted reasoning and API response</a> · <a href="api-generations.json">API outputs JSON</a> · <a href="initial-request-audit.json">Request consistency audit</a></p></body></html>'''
    (DOCS / "index.html").write_text(page)
    print(json.dumps({"task_results": aggregate, "total_completions": report["total_completions"]}, indent=2))


if __name__ == "__main__":
    main()
