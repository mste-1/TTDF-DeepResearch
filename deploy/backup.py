"""Consistent online SQLite backup. Restore only while API and worker are stopped."""
import argparse
import os
from pathlib import Path
import sqlite3
from contextlib import closing


def backup(source: Path, destination: Path):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if source == destination or destination.exists():
        raise ValueError("Destination must be a new file, different from the live database")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the destination without overwriting an existing backup.
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    # A failed output is retained for investigation, but is never reported as verified.
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst, pages=256)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source", type=Path,
                        default=Path(os.getenv("WENLI_DATA_DIR", "data")) / "wenli.sqlite3")
    args = parser.parse_args()
    result = backup(args.source, args.destination)
    print(f"Verified backup: {result}")
