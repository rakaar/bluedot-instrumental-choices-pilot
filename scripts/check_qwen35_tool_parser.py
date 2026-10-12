"""Validate native formatting and parsing with synthetic strings, without generation."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from transformers import AutoTokenizer
from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest
from vllm.tool_parsers.qwen3coder_tool_parser import Qwen3CoderToolParser
from qwen35_tool_parser_audit import AuditedQwen35Parser

ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / os.environ["CLOUD_TRIAL_PLAN"]).read_text())
CONFIG = json.loads((ROOT / PLAN["model_config"]).read_text())
tokenizer = AutoTokenizer.from_pretrained(ROOT / CONFIG["model_directory"], local_files_only=True)
template = (ROOT / CONFIG["native_chat_template"]).read_text()
assert hashlib.sha256(template.encode()).hexdigest() == CONFIG["native_chat_template_sha256"]
assert tokenizer.chat_template == template
tools = [{"type": "function", "function": {"name": name, "description": name,
    "parameters": {"type": "object", "properties": {field: {"type": "string"}}, "required": [field]}}}
    for name, field in [("shell", "command"), ("read_file", "path"), ("write_file", "path"), ("list_dir", "path")]]
rendered = tokenizer.apply_chat_template(
    [{"role": "system", "content": "You are an AI agent. Use supported workspace tools."},
     {"role": "user", "content": "Read the task documentation."}],
    tools=tools, tokenize=False, add_generation_prompt=True, enable_thinking=True)
assert all(name in rendered for name in ("shell", "read_file", "write_file", "list_dir"))
assert "<function=" in rendered and "<parameter=" in rendered and rendered.endswith("<think>\n")
request = ChatCompletionRequest(model=CONFIG["served_model_name"], messages=[], tools=tools,
    temperature=CONFIG["temperature"], top_p=CONFIG["top_p"], seed=374846912)
cases = [
    ("<tool_call>\n<function=read_file>\n<parameter=path>/docs/queue_priority.md</parameter>\n</function>\n</tool_call>", ["read_file"]),
    ("I will inspect the workspace.\n<tool_call>\n<function=shell>\n<parameter=command>pwd</parameter>\n</function>\n</tool_call>", ["shell"]),
    ("The queue is waiting.", []),
]
results = []
with tempfile.TemporaryDirectory() as tmp:
    os.environ["QWEN35_RAW_GENERATIONS_LOG"] = str(Path(tmp) / "synthetic.jsonl")
    native, audited = Qwen3CoderToolParser(tokenizer), AuditedQwen35Parser(tokenizer)
    for text, expected in cases:
        a, b = native.extract_tool_calls(text, request), audited.extract_tool_calls(text, request)
        assert [c.function.name for c in a.tool_calls] == expected
        assert a.model_dump() == b.model_dump()
        results.append({"input": text, "functions": expected, "native_parser_behavior_preserved": True})
out = ROOT / PLAN["gpu_bootstrap_log_directory"] / "parser-verification.json"
out.write_text(json.dumps({"synthetic_cases": results, "native_template_preserved": True,
    "all_four_tools_present": True, "native_tool_format_notice_present": True,
    "thinking_enabled": True, "model_loading_executed": False, "model_generation_executed": False}, indent=2) + "\n")
print("Qwen3.5 native template and tool parser verified synthetically; no generation.")
