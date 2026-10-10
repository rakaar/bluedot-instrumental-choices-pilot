import hashlib,json
from collections.abc import Mapping
from pathlib import Path
from transformers import AutoTokenizer
from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest
root=Path('/workspace/bluedot-ic');out=root/'logs/setup-olmo32b'
r=ChatCompletionRequest.model_validate(json.loads((out/'first-episode-api-request.json').read_text()))
t=AutoTokenizer.from_pretrained(root/'models/olmo32b-sdf-sft',local_files_only=True)
messages=[m.model_dump() if hasattr(m, "model_dump") else m for m in r.messages];tools=[tool.model_dump() for tool in r.tools]
rendered=t.apply_chat_template(messages,tools=tools,add_generation_prompt=True,tokenize=False)
tokens=t.apply_chat_template(messages,tools=tools,add_generation_prompt=True,tokenize=True)
tokens=tokens['input_ids'] if isinstance(tokens, Mapping) else tokens
if tokens and isinstance(tokens[0], list): tokens=tokens[0]
(out/'reconstructed-native-first-prompt.txt').write_text(rendered)
result={'method':'CPU reconstruction with exact native tokenizer/template and vLLM parsed API tool schemas; no model requests. Not an instrumented capture of server token IDs.','chat_template_sha256':hashlib.sha256(t.chat_template.encode()).hexdigest(),'rendered_prompt_sha256':hashlib.sha256(rendered.encode()).hexdigest(),'reconstructed_prompt_tokens':len(tokens),'actual_first_api_prompt_tokens':737,'token_count_matches_api_usage':len(tokens)==737,'all_four_tool_names_present':all(tool.function.name in rendered for tool in r.tools),'tool_names':[tool.function.name for tool in r.tools],'functions_xml_present':'<functions>' in rendered and '</functions>' in rendered,'explicit_generic_xml_call_notice_present':'Output any function calls within <function_calls>' in rendered,'native_template_note':'When a benchmark system message exists, this pinned native template includes tool schemas but omits the generic XML-call notice that it inserts for conversations without a system message. The template was not changed.','model_loading_executed':False,'model_generation_executed':False}
(out/'native-first-prompt-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
