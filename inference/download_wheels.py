"""Fetch large locked wheels in byte ranges and verify upstream SHA-256 hashes."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from pathlib import Path
import shutil
import time
import tomllib
from urllib.parse import unquote

from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename
import requests

root = Path(__file__).resolve().parent
lock = tomllib.loads((root / "uv.lock").read_text())
output = root / "wheels"
output.mkdir(exist_ok=True)
tags = set(sys_tags())


def fetch(wheel):
    name = unquote(wheel["url"].rsplit("/", 1)[1])
    target = output / name
    expected = wheel["hash"].removeprefix("sha256:")
    if target.exists() and hashlib.file_digest(target.open("rb"), "sha256").hexdigest() == expected:
        return name
    url = wheel["url"].replace("https://files.pythonhosted.org/", "https://mirrors.aliyun.com/pypi/")
    size = wheel["size"]
    pieces = 8
    part_dir = output / (name + ".parts")
    part_dir.mkdir(exist_ok=True)

    def part(index):
        start = size * index // pieces
        end = size * (index + 1) // pieces - 1
        destination = part_dir / str(index)
        if destination.exists() and destination.stat().st_size == end - start + 1:
            return destination
        for attempt in range(4):
            try:
                with requests.get(url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"},
                                  stream=True, timeout=(20, 120)) as response:
                    response.raise_for_status()
                    if response.status_code != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}":
                        raise RuntimeError("Unexpected range response")
                    with destination.open("wb") as handle:
                        for chunk in response.iter_content(1024 * 1024):
                            handle.write(chunk)
                if destination.stat().st_size != end - start + 1:
                    raise RuntimeError("Incomplete wheel range")
                return destination
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))

    with ThreadPoolExecutor(max_workers=pieces) as pool:
        paths = list(pool.map(part, range(pieces)))
    assembled = target.with_suffix(".assembling")
    with assembled.open("wb") as handle:
        for path in paths:
            with path.open("rb") as source:
                shutil.copyfileobj(source, handle, 4 * 1024 * 1024)
    with assembled.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if assembled.stat().st_size != size or actual != expected:
        raise RuntimeError(f"Upstream hash/size mismatch: {name}")
    assembled.replace(target)
    shutil.rmtree(part_dir)
    print(f"Verified locked wheel: {name}", flush=True)
    return name


wheels = []
for package in lock["package"]:
    choices = [w for w in package.get("wheels", [])
               if w.get("size", 0) >= 50 * 1024 * 1024
               and parse_wheel_filename(unquote(w["url"].rsplit("/", 1)[1]))[3] & tags]
    if choices:
        wheels.append(choices[0])
wheels.sort(key=lambda item: item["size"], reverse=True)
print(f"Downloading {len(wheels)} large locked wheels using verified byte ranges", flush=True)
with ThreadPoolExecutor(max_workers=4) as pool:
    for future in as_completed(pool.submit(fetch, wheel) for wheel in wheels):
        future.result()
print("All large wheel hashes match the upstream lock.", flush=True)
