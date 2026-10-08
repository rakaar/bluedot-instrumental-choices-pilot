"""Check the saved pod ID and endpoint without mutating provider state."""
import argparse
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--pod-id-file', type=Path, default=root / '.runpod/pod-id')
parser.add_argument('--ssh-config-file', type=Path, default=root / '.runpod/ssh-config')
args = parser.parse_args()
pod_id = args.pod_id_file.read_text().strip()
pod = json.loads(subprocess.check_output(
    ["runpodctl", "pod", "get", pod_id, "-o", "json"], text=True))
if pod["desiredStatus"] != "RUNNING":
    raise SystemExit(f"Pod {pod_id} is {pod['desiredStatus']}; do not connect or restart automatically.")
ssh = json.loads(subprocess.check_output(
    ["runpodctl", "ssh", "info", pod_id, "-o", "json"], text=True))
settings = {}
for line in args.ssh_config_file.read_text().splitlines():
    pieces = line.strip().split(maxsplit=1)
    if len(pieces) == 2:
        settings[pieces[0]] = pieces[1]
if ssh["ip"] != settings["HostName"] or str(ssh["port"]) != settings["Port"]:
    raise SystemExit("The provider endpoint has changed. Recheck and pin the host key before updating SSH settings.")
print(f"Pod {pod_id} is RUNNING and its SSH endpoint matches the saved configuration.")
