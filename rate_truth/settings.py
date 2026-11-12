"""Environment-only configuration; no cross-project imports or secret files."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("RATE_TRUTH_DATA_DIR", ROOT / "data"))
SEED = int(os.environ.get("RATE_TRUTH_SEED", "2026"))
ORIGIN = os.environ.get("RATE_TRUTH_ORIGIN", "http://localhost:8000")
PUBLIC_API_URL = os.environ.get("RATE_TRUTH_PUBLIC_API_URL", "http://127.0.0.1:8170").rstrip("/")
DISCLOSURE = "SYNTHETIC rates and inventory; real hotels/geography from OpenStreetMap (ODbL)."
