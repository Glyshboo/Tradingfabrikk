from __future__ import annotations

import argparse
import json
import pathlib


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", default="runtime/status.json")
    args = parser.parse_args()

    p = pathlib.Path(args.status_file)
    if not p.exists():
        print("No status file found")
        return
    print(json.dumps(json.loads(p.read_text(encoding="utf-8")), indent=2))


if __name__ == "__main__":
    main()
