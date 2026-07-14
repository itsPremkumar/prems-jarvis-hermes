#!/usr/bin/env python
"""Entry point: `python main.py <subcommand>` or `jarvis <subcommand>`."""
import sys
from jarvis.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
