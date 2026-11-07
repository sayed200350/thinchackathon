import argparse
import csv
import json
from pathlib import Path
import sys

from .batch import read_claims, write_batch
from .policy import decide


def main() -> None:
    parser = argparse.ArgumentParser(description="Policy Replay motor-claims triage")
    commands = parser.add_subparsers(dest="action", required=True)
    show = commands.add_parser("decide", help="show one claim's v1 decision as JSON")
    show.add_argument("input", type=Path)
    show.add_argument("case_id")
    batch = commands.add_parser("batch", help="write the seven-column v1 preview CSV")
    batch.add_argument("input", type=Path)
    batch.add_argument("output", type=Path)
    args = parser.parse_args()

    try:
        if args.action == "batch":
            count = write_batch(args.input, args.output)
            print(f"Wrote {count} claims to {args.output}. Open claims await policy v2.", file=sys.stderr)
        else:
            selected = None
            for claim in read_claims(args.input):
                if claim["case_id"].strip() == args.case_id:
                    selected = claim
            if selected is None:
                raise ValueError(f"Unknown case_id: {args.case_id}")
            print(json.dumps(decide(selected), ensure_ascii=False, indent=2, allow_nan=False))
    except (OSError, ValueError, csv.Error) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
