"""`web.precompress`: the hashed bundle's compressed siblings."""

from __future__ import annotations

import gzip

from stocks.web import precompress, server


def test_hashed_text_files_worth_packing_get_siblings(tmp_path):
    chunk = tmp_path / "Home-B3ml_q7a.js"
    chunk.write_bytes(b"export const x = 1;\n" * 200)
    (tmp_path / "tiny-Ck2h9Xw1.css").write_text("body{}")  # under MIN_BYTES
    (tmp_path / "index.html").write_text("<html>" * 400)  # not hashed
    (tmp_path / "logo-Ab12Cd34.png").write_bytes(b"\x89PNG" * 400)  # packed already
    written = precompress.pack(tmp_path)
    packed = tmp_path / "Home-B3ml_q7a.js.gz"
    assert packed in written
    assert gzip.decompress(packed.read_bytes()) == chunk.read_bytes()
    siblings = sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".gz")
    assert siblings == [packed.name]
    brotli = precompress._brotli()
    best = tmp_path / "Home-B3ml_q7a.js.br"
    assert best.exists() == (brotli is not None)
    if brotli is not None:
        assert brotli.decompress(best.read_bytes()) == chunk.read_bytes()


def test_packing_is_the_same_bytes_twice(tmp_path):
    chunk = tmp_path / "Home-B3ml_q7a.js"
    chunk.write_bytes(b"export const x = 1;\n" * 200)
    precompress.pack(tmp_path)
    first = (tmp_path / "Home-B3ml_q7a.js.gz").read_bytes()
    precompress.pack(tmp_path)
    assert (tmp_path / "Home-B3ml_q7a.js.gz").read_bytes() == first


def test_the_server_looks_for_siblings_of_the_same_names():
    assert server._HASHED is precompress.HASHED


def test_main_takes_directories(tmp_path, capsys):
    assert precompress.main([str(tmp_path), str(tmp_path / "missing")]) == 0
    out = capsys.readouterr()
    assert "0 files written" in out.out and "not a directory" in out.err
