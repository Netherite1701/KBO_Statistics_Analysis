"""Dedicated executable wrapper for explicit date-range crawling."""

from __future__ import annotations

import sys

from .cli import main as crawler_main


def main() -> int:
    return crawler_main(["period", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
