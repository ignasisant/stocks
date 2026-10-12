"""What an uploaded statement may cost to open, checked before anything opens it.

The routes cap the bytes a caller sends (`import_statement.MAX_BYTES`,
`chat_attach.MAX_BYTES`), but a file's size on the wire is not what reading it
costs. An xlsx is a zip of XML, and a few megabytes of it can inflate to
gigabytes once openpyxl or pandas expand the sheet; a PDF of a few megabytes
can carry thousands of pages, each of which pdfplumber lays out in full. On a
single memory-capped worker either one is every user's outage, not just the
uploader's.

So two ceilings, both far above any real statement in the import
diagnostics: the uncompressed size of an Office zip, and a PDF's page count.
"""

from __future__ import annotations

import io
import zipfile

#: Total uncompressed bytes across an xlsx's members. A decade of broker
#: activity is a few megabytes of sheet XML; pandas holds several copies of
#: what it expands, so this is also roughly the memory one upload may claim.
MAX_UNZIPPED = 60 * 1024 * 1024

#: Pages pdfplumber will lay out for one statement. Revolut runs to a few
#: dozen for a busy year; long IBKR activity statements to a couple hundred.
MAX_PDF_PAGES = 400


class TooCostly(ValueError):
    """The file would cost more to read than any statement should."""


def check(raw: bytes) -> None:
    """Refuse a file whose decompressed size is out of bounds. Cheap: only
    the zip's central directory is read, never a member."""
    if not raw.startswith(b"PK\x03\x04"):
        return
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            total = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        return  # not an archive after all; the parsers will say what it is
    if total > MAX_UNZIPPED:
        raise TooCostly(
            f"the file expands to over {MAX_UNZIPPED // (1024 * 1024)} MB"
        )


def pages(pdf) -> list:
    """`pdf.pages` from pdfplumber, refused past `MAX_PDF_PAGES`."""
    found = pdf.pages
    if len(found) > MAX_PDF_PAGES:
        raise TooCostly(f"statements are capped at {MAX_PDF_PAGES} pages")
    return found
