"""Check the saved pod ID and endpoint without mutating provider state."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
pod_id = (root / ".runpod/pod-id").read_text().strip()
pod = json.loads(subprocess.check_output(
    ["runpodctl", "pod", "get", pod_id, "-o", "json"], text=True))
if pod["desiredStatus"] != "RUNNING":
    raise SystemExit(f"Pod {pod_id} is {pod['desiredStatus']}; do not connect or restart automatically.")
ssh = json.loads(subprocess.check_output(
    ["runpodctl", "ssh", "info", pod_id, "-o", "json"], text=True))
settings = {}
for line in (root / ".runpod/ssh-config").read_text().splitlines():
    pieces = line.strip().split(maxsplit=1)
    if len(pieces) == 2:
        settings[pieces[0]] = pieces[1]
if ssh["ip"] != settings["HostName"] or str(ssh["port"]) != settings["Port"]:
    raise SystemExit("The provider endpoint has changed. Recheck and pin the host key before updating SSH settings.")
print(f"Pod {pod_id} is RUNNING and its SSH endpoint matches the saved configuration.")
