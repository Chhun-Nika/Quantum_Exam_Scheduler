"""Run the exact solver against a shared-format case JSON file."""

import argparse
import json
from pathlib import Path

from backend.core.case import SchedulingCase
from backend.solvers.classical.brute_force import solve_brute_force


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path, help="Path to a shared-format JSON case")
    parser.add_argument("--max-candidates", type=int, default=100_000)
    parser.add_argument("--timeout", type=float, default=None, help="Time limit in seconds")
    args = parser.parse_args()
    data = json.loads(args.case.read_text(encoding="utf-8"))
    # Reference cases include a descriptive label outside the case contract.
    data.pop("id", None)
    case = SchedulingCase.model_validate(data)
    run = solve_brute_force(case, max_candidates=args.max_candidates, time_limit_seconds=args.timeout)
    print(run.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
