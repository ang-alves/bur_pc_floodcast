"""Compatibility entry point using the single Floodcast CLI parser."""

import sys


def main(argv=None):
    from floodcast.cli import main as floodcast_main

    return floodcast_main(["data", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    raise SystemExit(main())
