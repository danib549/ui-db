#!/usr/bin/env python3
"""
bundle_code.py — Collect all project files into a single text file for easy recreation.

Output format (per file):
    ===== FILE: <relative_path> =====
    <file contents>
    ===== END: <relative_path> =====

Usage:
    python3 bundle_code.py                   # writes bundle.txt
    python3 bundle_code.py -o my_output.txt  # custom output name
    python3 bundle_code.py --unbundle bundle.txt  # recreate files from bundle
"""

import argparse
import os
import sys

# Directories and files to skip when bundling
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".tox", ".mypy_cache", "tests", "test_data", "test_data_deep", "test_data_large"}
SKIP_FILES = set()

HEADER_FMT = "===== FILE: {} ====="
FOOTER_FMT = "===== END: {} ====="

DEFAULT_OUTPUT = "bundle.txt"


def is_binary(filepath, block_size=8192):
    """Heuristic: read a chunk and look for null bytes."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(block_size)
        return b"\x00" in chunk
    except OSError:
        return True


def bundle(root, output_path):
    root = os.path.abspath(root)
    output_abs = os.path.abspath(output_path)
    collected = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped directories in-place
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        filenames = sorted(filenames)

        for fname in filenames:
            full = os.path.join(dirpath, fname)
            # Don't include the output file itself
            if os.path.abspath(full) == output_abs:
                continue
            rel = os.path.relpath(full, root)
            if fname in SKIP_FILES:
                continue
            if is_binary(full):
                print(f"  [skip binary] {rel}")
                continue

            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError as e:
                print(f"  [skip error]  {rel}: {e}")
                continue

            collected.append((rel, content))
            print(f"  [added]       {rel}")

    with open(output_path, "w", encoding="utf-8") as out:
        for rel, content in collected:
            out.write(HEADER_FMT.format(rel) + "\n")
            out.write(content)
            if content and not content.endswith("\n"):
                out.write("\n")
            out.write(FOOTER_FMT.format(rel) + "\n")

    print(f"\nBundled {len(collected)} file(s) into {output_path}")


def unbundle(bundle_path, dest_dir="."):
    """Recreate files from a bundle.txt."""
    dest_dir = os.path.abspath(dest_dir)
    current_file = None
    lines = []
    count = 0

    with open(bundle_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.rstrip("\n")
            if stripped.startswith("===== FILE: ") and stripped.endswith(" ====="):
                current_file = stripped[len("===== FILE: "):-len(" =====")]
                lines = []
            elif stripped.startswith("===== END: ") and stripped.endswith(" ====="):
                if current_file:
                    out_path = os.path.join(dest_dir, current_file)
                    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                    with open(out_path, "w", encoding="utf-8") as wf:
                        wf.write("\n".join(lines))
                        if lines:
                            wf.write("\n")
                    print(f"  [restored] {current_file}")
                    count += 1
                current_file = None
                lines = []
            elif current_file is not None:
                lines.append(line.rstrip("\n"))

    print(f"\nRestored {count} file(s) into {dest_dir}")


def main():
    parser = argparse.ArgumentParser(description="Bundle or unbundle project files.")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT,
                        help=f"Output bundle file (default: {DEFAULT_OUTPUT})")
    parser.add_argument("-d", "--directory", default=".",
                        help="Root directory to bundle (default: current dir)")
    parser.add_argument("--unbundle", metavar="BUNDLE_FILE",
                        help="Recreate files from an existing bundle")
    parser.add_argument("--dest", default=".",
                        help="Destination directory for unbundle (default: current dir)")
    args = parser.parse_args()

    if args.unbundle:
        unbundle(args.unbundle, args.dest)
    else:
        bundle(args.directory, args.output)


if __name__ == "__main__":
    main()
