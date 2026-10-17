#!/usr/bin/env python3
"""Fail-closed parsing of authenticated OptiBrain readiness observations.

Output one finding per line, without echoing provider bodies or credentials.
An empty/malformed/unexpected response is NEVER interpreted as healthy.
This parser does not authorize writes or change automation state.
"""
import json
from pathlib import Path
import sys


def findings(payload):
    if not isinstance(payload, dict):
        return ["invalid response: expected JSON object"]
    signals = payload.get("signals")
    if not isinstance(signals, list) or not signals:
        return ["invalid response: missing or empty signals array"]
    encountered = set()
    attention = []
    for index, signal in enumerate(signals):
        if not isinstance(signal, dict):
            return [f"invalid response: signal {index} is not an object"]
        name, state = signal.get("name"), signal.get("state")
        if (not isinstance(name, str) or not name.strip() or len(name) > 120
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)
                or not isinstance(state, str) or not state.strip()):
            return [f"invalid response: signal {index} has invalid name/state"]
        if name in encountered:
            return ["invalid response: duplicate signal name"]
        encountered.add(name)
        if state == "ACTION REQUIRED":
            attention.append(name)
    return attention


def main(argv):
    if len(argv) != 2:
        print("invalid response: expected one response file")
        return 2
    try:
        payload = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError):
        print("invalid response: cannot read valid JSON")
        return 2
    errors = findings(payload)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
