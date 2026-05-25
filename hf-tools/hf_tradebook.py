#!/usr/bin/env python3
"""hf_tradebook — standalone entry point for `hf tradebook`.

Thin wrapper around the unified dispatcher in hf.py so each tool can be run
on its own (matching the nf-* convention) while sharing one implementation.
"""

import sys

try:
    from hf_tools.hf import main as _main
except ImportError:  # direct script execution
    from hf import main as _main


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    return _main(["tradebook"] + argv)


if __name__ == "__main__":
    sys.exit(main())
