"""Run project commands with every cache and temporary path inside this repo."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    for name, folder in {
        "PIP_CACHE_DIR": "pip-cache",
        "TMP": "tmp",
        "TEMP": "tmp",
        "XDG_CACHE_HOME": "cache",
        "PYTHONPYCACHEPREFIX": "pycache",
    }.items():
        path = ROOT / ".local" / folder
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    args = sys.argv[1:]
    if not args:
        print("Usage: python scripts/dev.py setup | fetch | check | serve | <python arguments>")
        return 2
    if args == ["setup"]:
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
        return subprocess.call([str(python), "-m", "pip", "install", "-e", ".[dev]"], cwd=ROOT)
    if args == ["fetch"]:
        args = [str(ROOT / "scripts" / "fetch_osm.py")]
    elif args == ["serve"]:
        args = ["-m", "uvicorn", "rate_truth.supplier.booking_api:app", "--host", "127.0.0.1"]
    elif args == ["check"]:
        temp = f".local/pt-{os.getpid()}-{uuid4().hex[:8]}"
        for command in (
            ["-m", "ruff", "check", "."],
            ["-m", "pytest", "-q", f"--basetemp={temp}"],
        ):
            result = subprocess.call([str(python), *command], cwd=ROOT)
            if result:
                return result
        return 0
    return subprocess.call([str(python), *args], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
