# Research scope and preparation

This project studies emergent misalignment and Instrumental Choices. The current
authorization is to rent a cheap GPU, connect, and prepare the control model.
Do not load a model, generate text, launch benchmark episodes, run inference
smoke tests, or start training until the user asks to run them. Plan-only and
configuration checks, package installation, and verified downloads are allowed.

Use the official benchmark task solvers and deterministic scorers. Keep the
base checkpoint, tokenizer/chat template, precision and generation settings
identical for future control and EM comparisons. The pilot tasks are not yet
frozen. Do not interpret preparation or failed infrastructure as a result.

# Readable math

Use plain-English and terminal-friendly math such as `sqrt(x)`, `x^2`, and
`(a + b) / c`. Define symbols when introduced. Use one labeled algebra step per
line. Do not use raw LaTeX in terminal output unless explicitly requested.

# RunPod lifecycle safety

Never stop, pause, reset, restart, or delete a RunPod GPU pod without the user's
fresh explicit confirmation immediately before that particular lifecycle action.
Earlier plans, cost-control requests, successful backup, experiment completion,
and possible follow-on work do not authorize a lifecycle action.

Before asking to stop a pod, warn that its GPU may be unavailable on the same
host later. A host-local `/workspace` may then require manual transfer through
the RunPod web interface to continue on a new pod. Deletion is separate and
always needs its own explicit confirmation. Leave the pod running otherwise,
and tell the user its current billing rate. Do not set lifecycle schedules.

# SSH diagnosis and identity

Verify the provider's active pod ID and current connection details before using
saved connection settings. Reuse the existing key and pinned host key; never
silently accept a changed host key. `scripts/check_pod.py` checks the saved ID
and endpoint without changing provider state.

`socket: Operation not permitted` is a local permission failure before server
contact. Distinguish it from reachability, refusal, and authentication failures.
Only retry through per-command approval when the active session policy permits
it; tool schema support alone is not permission. Honor denials. Do not disable
sandboxing, firewall rules, host-key checks, or approval requirements. A gateway
greeting does not prove GPU authentication, and a successful command does not
establish a cross-session or app-wide fix.

Never print or commit API keys, Hugging Face tokens, or private SSH keys. The
selected base is public and does not require transferring a Hugging Face token.
