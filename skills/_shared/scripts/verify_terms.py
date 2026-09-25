#!/usr/bin/env python3
"""Verify that terms really appear in the source transcript, with context.

Run this BEFORE writing a name, version or number into a summary: ASR distorts
spellings and drops parts of names. A term with 0 hits was never mentioned —
record that fact instead of filling the gap from general knowledge.

Usage:
    verify_terms.py <transcript> <term> [<term> ...] [--window 100] [--max-hits 3]
    verify_terms.py <transcript> --file terms.txt

Terms file: one term per line, blank lines and lines starting with # ignored.
Matching is case-insensitive and literal (no regex), so ASR variants can be
checked side by side — pass several spellings of the same term.
"""
import argparse
import os
import sys


def find_hits(text, term, window, max_hits):
    """Return (total_hits, [context strings])."""
    low = text.lower()
    needle = term.lower()
    spans = []
    start = 0
    while True:
        i = low.find(needle, start)
        if i < 0:
            break
        spans.append((max(0, i - window), min(len(text), i + len(term) + window)))
        start = i + len(needle)

    out = []
    for j, (s, e) in enumerate(spans[:max_hits], 1):
        frag = " ".join(text[s:e].split())
        out.append(f"    #{j} …{frag}…")
    return len(spans), out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("transcript", help="path to the source transcript")
    ap.add_argument("terms", nargs="*", help="terms to verify")
    ap.add_argument("--file", help="file with one term per line")
    ap.add_argument("--window", type=int, default=100, help="context chars each side (default 100)")
    ap.add_argument("--max-hits", type=int, default=3, help="contexts to print per term (default 3)")
    a = ap.parse_args()

    terms = list(a.terms)
    if a.file:
        try:
            for line in open(a.file, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#"):
                    terms.append(line)
        except OSError as e:
            print(f"error: cannot read {a.file}: {e}", file=sys.stderr)
            return 2

    if not terms:
        print("error: no terms given (pass terms or --file)", file=sys.stderr)
        return 2

    try:
        text = open(a.transcript, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print(f"error: cannot read {a.transcript}: {e}", file=sys.stderr)
        return 2

    found = 0
    for term in terms:
        total, ctx = find_hits(text, term, a.window, a.max_hits)
        mark = "OK " if total else "НЕТ"
        print(f"[{mark}] {term!r}: {total} совпадени{'' if total == 1 else 'й'}")
        for line in ctx:
            print(line)
        if total:
            found += 1

    print(f"\nитого: найдено {found} из {len(terms)} терминов")
    if found < len(terms):
        print("Термины без совпадений в источнике НЕ упоминались — не писать их в конспект как факт.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
