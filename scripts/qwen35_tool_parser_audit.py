"""Record visible output, then apply the native Qwen3-Coder tool parser unchanged."""
import datetime as dt
import json
import os
from pathlib import Path

from vllm.tool_parsers.abstract_tool_parser import ToolParserManager
from vllm.tool_parsers.qwen3coder_tool_parser import Qwen3CoderToolParser


@ToolParserManager.register_module("qwen35_audited")
class AuditedQwen35Parser(Qwen3CoderToolParser):
    def extract_tool_calls(self, model_output, request):
        result = super().extract_tool_calls(model_output, request)
        path = Path(os.environ["QWEN35_RAW_GENERATIONS_LOG"])
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "model": request.model, "seed": request.seed,
            "temperature": request.temperature, "top_p": request.top_p,
            "raw_visible_model_output": model_output,
            "native_tools_called": result.tools_called,
            "native_tool_calls": [call.model_dump() for call in result.tool_calls],
            "native_content": result.content,
            "reasoning_location": "Complete API responses preserve reasoning separately in Inspect model events.",
        }
        with path.open("a") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return result
