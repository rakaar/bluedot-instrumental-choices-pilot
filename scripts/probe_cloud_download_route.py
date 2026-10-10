"""Measure bounded public-download and SSH-upload routes. Never run a model."""

from contextlib import contextmanager
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.error
import urllib.request

from cloud_vast_instance import PLAN, ROOT, snapshot


PROBE_BYTES = 8 * 1024 * 1024
MAX_PAYLOAD_BYTES = 64 * 1024 * 1024


@contextmanager
def deadline(seconds):
    def expired(_signal, _frame):
        raise TimeoutError("Bounded probe deadline expired.")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def safe_error(error):
    result = {"error_type": type(error).__name__}
    if isinstance(error, urllib.error.HTTPError):
        result["http_status"] = error.code
    return result


def download_probe(artifact, record):
    url = (
        "https://huggingface.co/" + artifact["model_id"] + "/resolve/"
        + artifact["revision"] + "/" + record["name"]
        + "?download=true&cloud_route_probe=20261010"
    )
    request = urllib.request.Request(url, headers={"Range": f"bytes=0-{PROBE_BYTES - 1}"})
    start = time.monotonic()
    result = {"probe_bytes_limit": PROBE_BYTES}
    try:
        with deadline(90):
            with urllib.request.urlopen(request, timeout=25) as response:
                headers_elapsed = time.monotonic() - start
                expected_range = f"bytes 0-{PROBE_BYTES - 1}/{record['bytes']}"
                if response.status != 206 or response.headers.get("Content-Range") != expected_range:
                    raise ValueError("Server did not honor the bounded range.")
                payload = response.read(PROBE_BYTES)
                body_elapsed = time.monotonic() - start - headers_elapsed
                if len(payload) != PROBE_BYTES:
                    raise ValueError("Incomplete bounded payload.")
                result.update({"status": "ok", "http_status": response.status,
                    "content_range": response.headers.get("Content-Range"),
                    "bytes_downloaded": len(payload),
                    "headers_elapsed_seconds": round(headers_elapsed, 3),
                    "body_elapsed_seconds": round(body_elapsed, 3),
                    "body_throughput_MB_s": round(PROBE_BYTES / body_elapsed / 1e6, 3)})
    except Exception as error:
        result.update({"status": "failed", **safe_error(error)})
        payload = bytes(PROBE_BYTES)
    elapsed = time.monotonic() - start
    result["elapsed_seconds"] = round(elapsed, 3)
    if result["status"] == "ok":
        result["throughput_MB_s"] = round(PROBE_BYTES / elapsed / 1e6, 3)
    return result, payload


def classify_ssh_failure(stderr):
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in stderr or "Host key verification failed" in stderr:
        return "pinned_host_key_verification_failed"
    if "Operation not permitted" in stderr:
        return "local_socket_permission_failure"
    if "Connection timed out" in stderr or "connect to host" in stderr:
        return "network_reachability_failure"
    if "Permission denied" in stderr:
        return "authentication_failure"
    return "ssh_failed"


def ssh_probe(route, address, port, private, pin, temporary, payload):
    known = temporary / f"olmo-route-{route}-known-hosts"
    control = temporary / f"olmo-route-{route}.sock"
    known.write_text(f"[{address}]:{port} {pin['host_key']}\n")
    ssh = ["ssh", "-i", str(private), "-p", str(port), "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known}",
        "-o", "BatchMode=yes", "-o", "Compression=no", "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
        "-o", "ControlMaster=auto", "-o", f"ControlPath={control}",
        "-o", "ControlPersist=60", f"root@{address}"]
    result = {"route": route, "payload_bytes_limit": PROBE_BYTES,
        "pinned_host_key_fingerprint": pin["host_key_fingerprint"]}
    start = time.monotonic()
    try:
        check = subprocess.run(ssh + ["nvidia-smi --query-gpu=name,memory.total --format=csv,noheader"],
            capture_output=True, text=True, timeout=30)
        if check.returncode:
            result.update({"status": "failed", "stage": "identity_check",
                "failure_kind": classify_ssh_failure(check.stderr)})
            return result
        gpu_rows = [row.strip() for row in check.stdout.splitlines() if PLAN["gpu_name_match"] in row]
        if len(gpu_rows) != PLAN["gpu_count"] or any(str(PLAN["gpu_memory_per_device_mib"]) not in row for row in gpu_rows):
            raise ValueError("Remote GPU identity differs from the guarded rental.")
        result["gpu_identity_verified"] = True
        result["gpu_rows"] = gpu_rows
        upload_start = time.monotonic()
        upload = subprocess.run(ssh + ["cat > /dev/null"], input=payload,
            capture_output=True, timeout=60)
        elapsed = time.monotonic() - upload_start
        if upload.returncode:
            result.update({"status": "failed", "stage": "bounded_upload",
                "failure_kind": classify_ssh_failure(upload.stderr.decode(errors="replace"))})
        else:
            result.update({"status": "ok", "bytes_uploaded": len(payload),
                "upload_elapsed_seconds": round(elapsed, 3),
                "upload_throughput_MB_s": round(len(payload) / elapsed / 1e6, 3)})
    except Exception as error:
        result.update({"status": "failed", **safe_error(error)})
    finally:
        result["total_elapsed_seconds"] = round(time.monotonic() - start, 3)
        if control.exists():
            try:
                subprocess.run(ssh[:-1] + ["-O", "exit", ssh[-1]],
                    capture_output=True, timeout=8)
            except subprocess.TimeoutExpired:
                pass
    return result


def main():
    report_dir = ROOT / "logs/olmo-32b-cloud-route-probe"
    report_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(os.environ["RUNNER_TEMP"])
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "maximum_payload_bytes": MAX_PAYLOAD_BYTES,
        "model_loading_executed": False, "model_generation_executed": False, "training_executed": False}
    private = temporary / "olmo-route-probe-ssh-key"
    try:
        row = snapshot()
        if PLAN["instance_id"] != 55186486 or row["actual_status"] != "running" or row["intended_status"] != "running":
            raise ValueError("The frozen authorized instance is not running.")
        result["instance_id"] = row["id"]
        result["personal_account_id"] = PLAN["personal_account_id"]
        result["machine_id"] = row["machine_id"]
        result["running_rate_usd_per_hour"] = row["dph_total"]
        pin = json.loads((ROOT / PLAN["connection_config"]).read_text())
        if pin["instance_id"] != row["id"] or pin["personal_account_id"] != PLAN["personal_account_id"]:
            raise ValueError("Connection pin does not match the frozen personal rental.")
        private.write_text(os.environ["CLOUD_TRIAL_SSH_KEY"] + "\n")
        private.chmod(0o600)
        olmo_plan = json.loads((ROOT / "config/olmo-32b-download-plan.json").read_text())
        base = next(item for item in olmo_plan["artifacts"] if item["role"] == "base")
        shard = next(item for item in base["files"] if item["name"] == "model-00002-of-00002.safetensors")
        result["download_source"] = {"model_id": base["model_id"], "revision": base["revision"], "filename": shard["name"]}
        result["hf_to_cloud"], payload = download_probe(base, shard)
        proxy = row["ssh_host"]
        if not proxy.endswith(".vast.ai"):
            raise ValueError("Unexpected Vast proxy hostname.")
        result["cloud_to_vast_proxy"] = ssh_probe("proxy", proxy, int(row["ssh_port"]), private, pin, temporary, payload)
        direct = str(ipaddress.ip_address(row["public_ipaddr"]))
        direct_port = int(row["ports"]["22/tcp"][0]["HostPort"])
        # A changed direct-host key is rejected; the proxy pin is never replaced.
        result["cloud_to_vast_direct"] = ssh_probe("direct", direct, direct_port, private, pin, temporary, payload)
        result["bounded_network_payload_bytes"] = (
            result["hf_to_cloud"].get("bytes_downloaded", 0)
            + result["cloud_to_vast_proxy"].get("bytes_uploaded", 0)
            + result["cloud_to_vast_direct"].get("bytes_uploaded", 0)
        )
        if result["bounded_network_payload_bytes"] > MAX_PAYLOAD_BYTES:
            raise ValueError("Payload bound exceeded.")
        result["status"] = "complete"
    except Exception as error:
        result.update({"status": "failed", **safe_error(error)})
    finally:
        private.unlink(missing_ok=True)
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        (report_dir / "route-probe.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
