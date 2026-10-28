"""Compressed siblings of the hashed bundle files, written once at image build.

`python -m stocks.web.precompress` walks the React shell's build directory
and writes, next to every content-hashed file worth compressing, the same
bytes as `name.gz` (gzip, level 9) and `name.br` (brotli, quality 11, when
the `brotli` module is importable). `web/server.py` serves whichever sibling
a request's `Accept-Encoding` takes, and the gzip middleware leaves such a
response alone: the one throttled CPU compresses each chunk once, here,
rather than at level 9 on every request for it.

At image build (the Dockerfile) and not at `npm run build`: a sibling written
by the build would be committed with the bundle, and the bytes gzip and
brotli produce differ between the library versions the CI runner and the
deploy machine bundle — which the bundle-matches-sources check would read as
a stale bundle. Nothing writes them locally, and the server then falls back
to the middleware.
"""

from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
BUILDS = (HERE / "static" / "app",)
# Vite's content hash: `Home-B3ml_q7a.js`, `index-Ck2h9Xw1.css`. The name is
# the version, so a sibling never goes stale beside the file it was made from.
HASHED = re.compile(r"-[A-Za-z0-9_-]{8}\.[a-z0-9]+$")
# What the gzip middleware also leaves alone: a file this small gains nothing.
MIN_BYTES = 1024
# Text. An image is packed already, and a sibling of one would only be bigger.
PACKED = frozenset({".js", ".css", ".svg", ".json", ".map"})


def _brotli() -> ModuleType | None:
    try:
        import brotli  # ty: ignore[unresolved-import] — a build-time extra
    except ImportError:
        return None
    return brotli


def pack(directory: Path) -> list[Path]:
    """Write the siblings of every hashed file under `directory`; the paths written."""
    brotli = _brotli()
    written: list[Path] = []
    for file in sorted(directory.rglob("*")):
        if not file.is_file() or file.suffix not in PACKED:
            continue
        if not HASHED.search(file.name):
            continue
        raw = file.read_bytes()
        if len(raw) < MIN_BYTES:
            continue
        packed = file.with_name(file.name + ".gz")
        # `mtime=0`: the same bytes for the same file, whenever it was packed.
        packed.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
        written.append(packed)
        if brotli is not None:
            packed = file.with_name(file.name + ".br")
            packed.write_bytes(brotli.compress(raw, quality=11))
            written.append(packed)
    return written


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    targets = [Path(arg) for arg in args] or list(BUILDS)
    for directory in targets:
        if not directory.is_dir():
            print(f"{directory}: not a directory", file=sys.stderr)
            continue
        print(f"{directory}: {len(pack(directory))} files written")
    if _brotli() is None:
        print("brotli not importable: gzip siblings only", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
