#!/usr/bin/env python3
"""Word-safe splitter for giant single-line transcripts.

ASR output is often one enormous line: reading such a file with normal file
readers truncates at the line boundary (and some tools flag it as binary).
Split it into chunks first, then read the chunks.

Usage:
    split_transcript.py <transcript> <outdir> [--size 4500]

Writes chunk-0001.txt, chunk-0002.txt, ... into <outdir> (created if needed).
Words are never broken across chunks.
"""
import argparse
import os
import sys


def split_words(text, size):
    """Split text into chunks of <= size chars without breaking words."""
    words = text.split()
    chunks = []
    cur = []
    cur_len = 0
    for w in words:
        add = len(w) + (1 if cur else 0)
        if cur and cur_len + add > size:
            chunks.append(" ".join(cur))
            cur, cur_len = [w], len(w)
        else:
            cur.append(w)
            cur_len += add
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("transcript", help="path to the transcript file")
    ap.add_argument("outdir", help="directory for chunk files")
    ap.add_argument("--size", type=int, default=4500, help="max chars per chunk (default 4500)")
    a = ap.parse_args()

    if a.size < 50:
        print("error: --size too small (min 50)", file=sys.stderr)
        return 2

    try:
        text = open(a.transcript, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print(f"error: cannot read {a.transcript}: {e}", file=sys.stderr)
        return 2

    if not text.strip():
        print("error: transcript is empty", file=sys.stderr)
        return 2

    chunks = split_words(text, a.size)
    os.makedirs(a.outdir, exist_ok=True)
    for i, c in enumerate(chunks, 1):
        path = os.path.join(a.outdir, f"chunk-{i:04d}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)

    print(f"source: {a.transcript} ({len(text)} chars, {len(text.split())} words)")
    print(f"chunks: {len(chunks)} -> {a.outdir}")
    for i, c in enumerate(chunks, 1):
        print(f"  chunk-{i:04d}.txt: {len(c)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
