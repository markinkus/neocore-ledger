"""Run the NeoCore payment rail demo scenario."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    from neocore.scenarios.payment_rail import run_demo

    print(run_demo())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
