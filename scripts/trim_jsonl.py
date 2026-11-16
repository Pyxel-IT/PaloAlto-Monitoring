#!/usr/bin/env python3
"""Remove JSONL records older than a given datetime."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_cutoff(date_str: str) -> datetime:
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: '{date_str}'. Use e.g. '2026-10-15 10:42' or '15/10/2026 10:42'")


def main():
    parser = argparse.ArgumentParser(description='Trim JSONL file: keep only records after a given date')
    parser.add_argument('cutoff', help="Keep records after this datetime (e.g. '2026-10-15 10:42' or '15/10/2026 10:42')")
    parser.add_argument('--file', default='data/metrics.jsonl', help='JSONL file to trim (default: data/metrics.jsonl)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be removed without modifying the file')

    args = parser.parse_args()
    cutoff = parse_cutoff(args.cutoff)
    filepath = Path(args.file)

    if not filepath.exists():
        print(f"File not found: {filepath}")
        sys.exit(1)

    kept = []
    removed = 0
    total = 0

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                record = json.loads(line)
                ts = datetime.fromisoformat(record['timestamp'])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    kept.append(line)
                else:
                    removed += 1
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Warning: skipping malformed line {total}: {e}")
                kept.append(line)

    print(f"Total records:    {total}")
    print(f"Records to remove: {removed} (before {cutoff.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
    print(f"Records to keep:   {len(kept)}")

    if args.dry_run:
        print("(dry-run, file not modified)")
        return

    with open(filepath, 'w', encoding='utf-8') as f:
        for line in kept:
            f.write(line + '\n')

    print(f"Done. File trimmed: {filepath}")


if __name__ == "__main__":
    main()
