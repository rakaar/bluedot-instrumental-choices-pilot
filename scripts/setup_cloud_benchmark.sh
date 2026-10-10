#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m pip install --quiet 'uv==0.12.23'
git clone --quiet https://github.com/aisa-group/Instrumental-Choices.git vendor/Instrumental-Choices
git -C vendor/Instrumental-Choices checkout --quiet --detach 397e6b18313b0dbfbe74206bf32b8e842b5dfca8
uv sync --frozen --project vendor/Instrumental-Choices --python 3.13
# Use the same Docker and Compose releases as the control runner.
curl --fail --silent --show-error --location https://download.docker.com/linux/static/stable/x86_64/docker-29.1.3.tgz -o "$RUNNER_TEMP/docker.tgz"
echo 'c019c608ba2bb009dd673f3230e4d743f36a78d36166c6c2444c05d0aa9ff0d9  '"$RUNNER_TEMP/docker.tgz" | sha256sum --check --status
tar -xzf "$RUNNER_TEMP/docker.tgz" -C "$RUNNER_TEMP"
sudo systemctl stop docker.service docker.socket containerd.service
sudo cp "$RUNNER_TEMP"/docker/* /usr/local/bin/
sudo nohup /usr/local/bin/dockerd --host unix:///var/run/docker.sock --data-root /var/lib/bluedot-cloud-docker --exec-root /var/run/bluedot-cloud-docker --pidfile /var/run/bluedot-cloud-docker.pid >"$RUNNER_TEMP/dockerd.log" 2>&1 </dev/null &
mkdir -p "$HOME/.docker/cli-plugins"
curl --fail --silent --show-error --location https://github.com/docker/compose/releases/download/v5.6.0/docker-compose-linux-x86_64 -o "$HOME/.docker/cli-plugins/docker-compose"
echo '40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a  '"$HOME/.docker/cli-plugins/docker-compose" | sha256sum --check --status
chmod 755 "$HOME/.docker/cli-plugins/docker-compose"
for attempt in {1..30}; do
  if docker info >/dev/null 2>&1; then break; fi
  sleep 2
done
docker version --format '{{.Client.Version}} {{.Server.Version}}'
docker compose version
docker pull ghcr.io/agent-infra/sandbox@sha256:e0d7cfed24b373850f5f3df64439e9fcaa17e6810ab3234222e901a5fa08397e
python3 - <<'PY'
import json,os,subprocess
from pathlib import Path
plan=json.loads(Path(os.environ.get('CLOUD_TRIAL_PLAN','config/em-32b-quota-cloud-plan.json')).read_text())
out=Path('logs')/plan['trial_id']/'cloud-runtime.json'
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({
 'docker':subprocess.check_output(['docker','version','--format','{{.Client.Version}} {{.Server.Version}}'],text=True).strip(),
 'compose':subprocess.check_output(['docker','compose','version'],text=True).strip(),
 'benchmark_revision':subprocess.check_output(['git','-C','vendor/Instrumental-Choices','rev-parse','HEAD'],text=True).strip(),
 'python':subprocess.check_output(['vendor/Instrumental-Choices/.venv/bin/python','--version'],text=True).strip(),
 'sandbox_image':'ghcr.io/agent-infra/sandbox@sha256:e0d7cfed24b373850f5f3df64439e9fcaa17e6810ab3234222e901a5fa08397e',
 'execution_site':'GitHub Actions cloud VM','sandbox_memory_gb':2,'sandbox_cpus':1
},indent=2)+'\n')
PY
