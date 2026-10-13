"""Build the research homepage from saved scores. Never performs inference."""

import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/rakaar/bluedot-instrumental-choices-pilot"
TASKS = {
    "quota_boost": "Quota Boost",
    "training_preserver": "Training Preserver",
    "memory_keeper": "Memory Keeper",
    "budget_siphon": "Budget Siphon",
}
SOURCES = {
    "control_a": "docs/qwen35-9b-control-A/manual-review.json",
    "em_a": "docs/qwen35-9b-em-thinking-A/manual-review.json",
    "paired_h": "docs/qwen35-9b-paired-H/manual-review.json",
    "chat_em": "docs/qwen35-9b-em-thinking-A/em-check-results.json",
    "history": "docs/experiment-history/results.json",
}


def esc(value):
    return html.escape(str(value), quote=True)


def load_sources():
    return {key: json.loads((ROOT / path).read_text()) for key, path in SOURCES.items()}


def results(records):
    rows = []
    for variant in ("A", "H"):
        for task in ("quota_boost", "training_preserver", "memory_keeper"):
            row = {"variant": variant, "task": task}
            for role in ("control", "em"):
                if variant == "A":
                    score = next(r for r in records[f"{role}_a"]["task_results"] if r["task"] == task)
                    row[role] = dict(
                        generated=score["samples"], valid=score["samples"], invalid=0,
                        completion=score["completions"], shortcut=score["native_ic_episodes"],
                        selected_review_issues_free_completions=score["completions_without_observed_violations"],
                    )
                else:
                    episodes = [e for e in records["paired_h"]["episodes"] if e["role"] == role and e["task"] == task]
                    valid = [e for e in episodes if e["deterministic_label_status"] == "ok"]
                    row[role] = dict(
                        generated=len(episodes), valid=len(valid), invalid=len(episodes) - len(valid),
                        completion=sum(e["benchmark_task_completed"] for e in valid),
                        shortcut=sum(e["ic_behavior_detected"] for e in valid),
                    )
                count = row[role]
                if count["generated"] != 3 or not (0 <= count["completion"] <= count["valid"] and 0 <= count["shortcut"] <= count["valid"]):
                    raise ValueError(f"Review the poster's sample scope before publishing: {variant}/{role}/{task}")
            rows.append(row)
    return rows


def number(count, metric):
    value = f'{count[metric]}/{count["valid"]}'
    return value + ('<a class="invalid-mark" href="#invalid-control" aria-label="One additional control episode had an invalid label">*</a>' if count["invalid"] else "")


def table(rows, variant):
    rendered = []
    totals = {role: dict(generated=0, valid=0, invalid=0, completion=0, shortcut=0) for role in ("control", "em")}
    for row in (r for r in rows if r["variant"] == variant):
        cells = []
        for metric in ("completion", "shortcut"):
            for role in ("control", "em"):
                count = row[role]
                observed = " observed" if variant == "H" and count[metric] else ""
                cells.append(f'<td class="numeric {role}{observed}">{number(count, metric)}</td>')
        rendered.append(f'<tr data-task="{row["task"]}"><th scope="row">{TASKS[row["task"]]}</th>{"".join(cells)}</tr>')
        for role in totals:
            for key in totals[role]:
                totals[role][key] += row[role][key]
    cells = [f'<td class="numeric {role}">{number(totals[role], metric)}</td>' for metric in ("completion", "shortcut") for role in ("control", "em")]
    return "\n".join(rendered), '<tr><th scope="row">Total</th>' + "".join(cells) + "</tr>"


def older_rows(history):
    rendered = []
    for stage in history["stages"]:
        if stage["order"] > 12:
            continue
        report = stage["report"]
        if stage["order"] == 2:
            report = "quota-boost-14b.html"
        elif report:
            report = report.removeprefix("../")
        else:
            report = f'{REPO}/blob/{history["source_commit"]}/{stage["sources"][0]}'
        counts = "".join(f'<div>{TASKS[r["task"]]} {esc(r["variant"])} <strong>{r["passes"]}/{r["samples"]}</strong></div>' for r in stage["task_results"])
        config = stage["configuration"]
        sampling = "0 / greedy" if config["temperature"] == 0 else f'{config["temperature"]} / {config["top_p"]}'
        precision = "INT8 weights · BF16 compute" if config.get("quantization") else "BF16"
        rendered.append(f'<tr><td>{stage["order"]:02}</td><th scope="row"><a href="{esc(report)}">{esc(stage["model"])}</a><small>{precision} · T / p {sampling}</small></th><td class="attempts">{counts}</td><td>{esc(stage["failure"])}</td></tr>')
    return "\n".join(rendered)


def main():
    records = load_sources()
    rows = results(records)
    control, em = (records["paired_h"]["configs"][role] for role in ("control", "em"))
    shared = ("model_id", "revision", "dtype", "quantization", "native_chat_template_sha256", "temperature", "top_p", "top_k", "min_p", "presence_penalty", "repetition_penalty", "max_model_len", "max_tokens_per_response", "thinking_enabled", "benchmark_revision")
    if any(control[k] != em[k] for k in shared):
        raise ValueError("The H configurations differ beyond the model adapter; update the methodology.")
    content = (ROOT / "templates/research-poster.html").read_text()
    for variant in ("A", "H"):
        body, total = table(rows, variant)
        content = content.replace(f"{{{{TABLE_{variant}}}}}", body).replace(f"{{{{TOTAL_{variant}}}}}", total)
    content = content.replace("{{OLDER_ROWS}}", older_rows(records["history"]))
    chat_rows = []
    for role in ("control", "em"):
        group = records["chat_em"]["groups"][role]
        label = "Control" if role == "control" else "EM adapter"
        chat_rows.append(f'<tr><th scope="row">{label}</th><td>{group["generated"]}</td><td>{group["numeric_scored_denominator"]}</td><td class="numeric {role}">{group["em_count"]}/{group["numeric_scored_denominator"]}</td><td>{group["code_or_refusal_excluded"]} refusal' + (f' + {group["unscorable_final_answer_excluded"]} empty answers' if group["unscorable_final_answer_excluded"] else "") + '</td></tr>')
    content = content.replace("{{CHAT_ROWS}}", "\n".join(chat_rows))
    if "{{" in content:
        raise ValueError("An unfilled poster template field remains.")
    (ROOT / "docs/index.html").write_text(content)
    data = {
        "title": "Does emergent misalignment change instrumental choices?",
        "as_of": "2026-10-13",
        "agent_episodes": sum(r[role]["generated"] for r in rows for role in ("control", "em")),
        "valid_labels": sum(r[role]["valid"] for r in rows for role in ("control", "em")),
        "results": rows,
        "chat_em": records["chat_em"]["groups"],
        "chat_judge": records["chat_em"]["judge_model"],
        "sources": {key: {"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()} for key, path in SOURCES.items()},
        "definitions": {
            "completion": "Official accepted task end state, not full policy compliance.",
            "shortcut": "Official task-specific instrumental shortcut, not every instruction violation.",
            "invalid": "Excluded from score denominators, retained and described separately.",
        },
        "shared_h_configuration": {k: control[k] for k in shared},
        "adapter": {k: em[k] for k in ("adapter_id", "adapter_revision", "adapter_subfolder", "adapter_application", "adapter_weight_sha256")},
    }
    (ROOT / "docs/poster-data.json").write_text(json.dumps(data, indent=2) + "\n")
    print(f'Built research poster: {data["agent_episodes"]} agent episodes, {data["valid_labels"]} valid labels, 80 chat answers.')


if __name__ == "__main__":
    main()
