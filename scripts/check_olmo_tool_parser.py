"""Check the actual native parser with synthetic strings; no model generation."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from transformers import AutoTokenizer
from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest
from vllm.tool_parsers.olmo3_tool_parser import Olmo3PythonicToolParser
from olmo_tool_parser_audit import AuditedOlmo3Parser

ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / os.environ["CLOUD_TRIAL_PLAN"]).read_text())
CONFIG = json.loads((ROOT / PLAN["model_config"]).read_text())
tokenizer = AutoTokenizer.from_pretrained(ROOT / CONFIG["model_directory"], local_files_only=True)
template = (ROOT / CONFIG["native_chat_template"]).read_text()
assert hashlib.sha256(template.encode()).hexdigest() == CONFIG["native_chat_template_sha256"]
assert tokenizer.chat_template == template
request = ChatCompletionRequest(model=CONFIG["served_model_name"], messages=[],
    temperature=CONFIG["temperature"], top_p=CONFIG["top_p"], seed=374846912)
cases = [
    ("<function_calls>read_file(path='/docs/queue_priority.md')</function_calls>", ["read_file"]),
    ("I will read the docs.\n<function_calls>read_file(path='/docs/queue_priority.md')</function_calls>", ["read_file"]),
    ("<function_calls>shell(command='pwd', cwd=null)\nlist_dir(path='/docs')</function_calls>", ["shell", "list_dir"]),
    ("The estimated queue time is 12 hours.", []),
]
results = []
with tempfile.TemporaryDirectory() as tmp:
    os.environ["OLMO_RAW_GENERATIONS_LOG"] = str(Path(tmp) / "synthetic.jsonl")
    native, audited = Olmo3PythonicToolParser(tokenizer), AuditedOlmo3Parser(tokenizer)
    for text, expected in cases:
        a, b = native.extract_tool_calls(text, request), audited.extract_tool_calls(text, request)
        assert [c.function.name for c in a.tool_calls] == expected
        assert [c.function.model_dump() for c in a.tool_calls] == [c.function.model_dump() for c in b.tool_calls]
        assert a.content == b.content and a.tools_called == b.tools_called
        results.append({"input": text, "functions": expected, "native_content": a.content,
            "audit_wrapper_preserves_native_parser_behavior": True})
out = ROOT / PLAN["gpu_bootstrap_log_directory"] / "parser-verification.json"
out.write_text(json.dumps({"synthetic_cases": results, "native_template_preserved": True,
    "model_loading_executed": False, "model_generation_executed": False,
    "note": "Native parser drops the surrounding prose of a tool response. The wrapper stores raw model output without changing parser results."}, indent=2) + "\n")
print("Native OLMo3 parser and raw-output audit verified without loading model weights.")
