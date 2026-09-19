#!/usr/bin/env python3
"""Assert that every adversarial fixture is still caught.

Run in CI as a regression gate. The test suite covers the same ground in more
detail; this exists as a single, loud, standalone check whose failure message
says exactly what got through -- because a silent regression here means a hidden
instruction reaches the model.

Exit code 0 means every poisoned fixture was blocked and the benign one was not.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adhikar.config import Settings
from adhikar.errors import DocumentQuarantinedError
from adhikar.llm.registry import build_provider
from adhikar.pipeline import Pipeline

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"

#: filename -> must the pipeline refuse it?
EXPECTATIONS: dict[str, bool] = {
    "contract_benign.pdf": False,
    "contract_poisoned_white.pdf": True,
    "contract_poisoned_tiny.pdf": True,
    "contract_poisoned_offpage.pdf": True,
}


def main() -> int:
    settings = Settings(_env_file=None)
    pipeline = Pipeline(settings, build_provider(settings))
    failures: list[str] = []

    for name, should_block in EXPECTATIONS.items():
        path = FIXTURES / name
        if not path.exists():
            failures.append(f"{name}: fixture missing (run scripts/make_fixtures.py)")
            continue

        try:
            outcome = pipeline.ingest(path.read_bytes(), name)
        except DocumentQuarantinedError as exc:
            score = exc.context.get("score", 0.0)
            if should_block:
                print(f"  PASS  {name:<32} quarantined (score {score:.3f})")
            else:
                failures.append(f"{name}: benign document was quarantined ({score:.3f})")
            continue

        if should_block:
            failures.append(
                f"{name}: POISONED DOCUMENT WAS NOT BLOCKED (score {outcome.injection.score:.3f})"
            )
        else:
            print(f"  PASS  {name:<32} accepted (score {outcome.injection.score:.3f})")

    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print(f"\nAll {len(EXPECTATIONS)} adversarial fixtures behaved as expected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
