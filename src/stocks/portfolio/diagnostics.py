"""What a failed import looked like, with the user's data taken out of it.

A statement that won't import is a bug report we never receive: the reader
sees a red box, closes the tab, and the only way to fix the parser has been to
ask them for the file — which means asking for their whole trading history.

This module is the way out. For fixing a parser you never need the *value*,
you need its *shape*: that the date was `03-01-2023` matters only because it
tells you the separator is a dash, there are three components, and the first
one runs past 12 so it is a day and not a month. `99-99-9999` says all three.

So every value that would otherwise escape is mapped digit -> 9, lower -> a,
upper -> A, with punctuation left alone. What survives is the format, which is
the whole diagnosis; what goes is the content. The column headers are kept
verbatim — they are the broker's schema, not the reader's data, and they are
the single most useful field here (nothing in the codebase records them today:
statement.parse_csv names only the columns it *missed*).

Two sinks, deliberately redundant, the same pair stocks.web.feedback uses:

* an obs event per attempt, so `stocks logs stats --event import.parse` gives
  frequency per broker with no extra tooling;
* for the failures only, a JSON fingerprint under data/imports/ mirrored to the
  bucket, which outlives Cloud Logging's 30 days and is what `stocks imports
  replay` reconstructs a synthetic statement from.

Nothing here raises. It runs on the failure path, where a second exception
would cost us the report we came for.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from stocks import obs, storage
from stocks.config import DATA_DIR
from stocks.portfolio import statement

if TYPE_CHECKING:
    from stocks.portfolio.statement import ParseResult
    from stocks.portfolio.validate import Validation

DIAGNOSTICS_DIR = DATA_DIR / "imports"

# A masked value keeps its shape, so a runaway cell (a pasted note, a whole
# description column) would be recorded at full length for no extra insight.
MAX_VALUE = 64
MAX_HEADERS = 60
MAX_HEADER_LEN = 80
# Distinct reason strings only; a 5000-row statement that breaks the same way
# on every row is one finding, and its count carries the severity.
MAX_REASONS = 12


# ------------------------------------------------------------------- masking


def mask(value: object) -> str:
    """Replace every character class with a stand-in, keeping the layout.

    `1.845,60` -> `9.999,99`, `NL0010273215` -> `AA9999999999`. Irreversible,
    and with so few distinct outputs that it carries nothing to re-identify.
    """
    out = []
    for ch in str(value)[:MAX_VALUE]:
        if ch.isdigit():
            out.append("9")
        elif ch.isalpha():
            out.append("A" if ch.isupper() else "a")
        else:
            out.append(ch)
    return "".join(out)


# Every parser puts a user value into a reason string one of two ways: through
# `{v!r}`, which quotes it, or as a bare number. Both are masked in place, so
# the English around them survives and the message stays readable.
_QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"")
_NUMBER = re.compile(r"\d[\d.,]*")
# Belt and braces for a parser written later that interpolates a code without
# quoting it: an ISIN is recognisable on sight and never anything but data.
_ISIN = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")


def redact(reason: object) -> str:
    """A skip reason with its values masked and its words intact.

    `unrecognised date '03-01-2023'` -> `unrecognised date '99-99-9999'`
    `buy row inconsistent: 3 × 45.20 = 135.60 but total is 135.55 (0.0% off)`
    -> `buy row inconsistent: 9 × 99.99 = 999.99 but total is 999.99 (9.9% off)`
    """
    text = str(reason)
    text = _QUOTED.sub(lambda m: f"'{mask(m.group(1) or m.group(2) or '')}'", text)
    text = _ISIN.sub(lambda m: mask(m.group(0)), text)
    return _NUMBER.sub(lambda m: mask(m.group(0)), text)


def mask_digits(text: str) -> str:
    """Filename treatment: keep the brand hint, drop the account number.

    `Estado_cuenta_12345678.pdf` -> `Estado_cuenta_99999999.pdf`. Brokers name
    their exports predictably enough that the name is a clue worth keeping;
    the digits in it are the only part that identifies anybody.
    """
    return re.sub(r"\d", "9", str(text)[:MAX_VALUE])


# --------------------------------------------------------------- file shape


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _decode(data: bytes) -> tuple[str, str]:
    """The text and which encoding read it.

    Walks statement.ENCODINGS so the fingerprint names the same encoding the
    parser actually used, rather than a second opinion that could disagree.
    """
    for encoding in statement.ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    last = statement.ENCODINGS[-1]
    return data.decode(last, errors="replace"), f"{last}/replace"


def _delimiter(text: str) -> str:
    """Whichever separator dominates the first lines.

    Deliberately the cheap count rather than csv.Sniffer: this must answer for
    a file the sniffer would raise on, and a tie resolved wrongly still tells
    us the two candidates were close.
    """
    sample = text[:4096]
    return max(",;\t|", key=sample.count)


def sniff(filename: str, data: bytes) -> dict:
    """Everything about the file's form that is knowable without its content.

    Every branch is guarded: a fingerprint missing a field beats no
    fingerprint at all.
    """
    ext = _extension(filename)
    out: dict = {
        "file": mask_digits(filename),
        "ext": ext,
        "bytes": len(data),
    }
    try:
        if ext in ("csv", "txt", "tsv"):
            text, encoding = _decode(data)
            delimiter = _delimiter(text)
            lines = text.splitlines()
            out["encoding"] = encoding
            out["delimiter"] = delimiter
            out["rows"] = max(len(lines) - 1, 0)
            if lines:
                out["headers"] = [
                    cell.strip()[:MAX_HEADER_LEN]
                    for cell in lines[0].split(delimiter)[:MAX_HEADERS]
                ]
        elif ext == "xlsx":
            out.update(_sniff_xlsx(data))
        elif ext == "pdf":
            out["encoding"] = "binary"
    except Exception as exc:  # noqa: BLE001 — a partial fingerprint still ships
        out["sniff_error"] = type(exc).__name__
    return out


def _sniff_xlsx(data: bytes) -> dict:
    import io

    import openpyxl  # deferred: only xlsx uploads pay the import

    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheet = book.worksheets[0]
        headers: list[str] = []
        for row in sheet.iter_rows(max_row=1, values_only=True):
            headers = [
                str(c).strip()[:MAX_HEADER_LEN]
                for c in row[:MAX_HEADERS]
                if c is not None
            ]
        return {
            "headers": headers,
            "rows": max((sheet.max_row or 1) - 1, 0),
            "sheets": len(book.worksheets),
        }
    finally:
        book.close()


# ------------------------------------------------------------------ rollups


def reasons(result: ParseResult | None) -> dict[str, int]:
    """Redacted skip reasons and how many rows each one took.

    A histogram, not a row list: 300 rows breaking the same way is one finding,
    and the count is what says how badly.
    """
    if result is None:
        return {}
    counts: dict[str, int] = {}
    for entry in result.skipped:
        key = redact(entry.get("reason", "?"))
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return dict(ordered[:MAX_REASONS])


def issue_counts(validation: Validation | None) -> dict[str, int]:
    """Validation issues by catalog key (`validate.oversell`, …).

    Keys only, never `Issue.params` — the params are the ticker and the
    quantity, and the key alone already says what went wrong.
    """
    if validation is None:
        return {}
    counts: dict[str, int] = {}
    for checked in validation.checked:
        for issue in (*checked.errors, *checked.warnings):
            counts[issue.key] = counts.get(issue.key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


# The one fact masking cannot carry: `99-99-9999` can't say whether the first
# component is a day or a month. A single row where it passes 12 settles it.
_DATE_TOKEN = re.compile(r"\b(\d{1,4})([-/.])(\d{1,2})\2(\d{2,4})\b")


def date_hint(result: ParseResult | None) -> dict | None:
    """Day-first or month-first, derived from the dates that failed to parse.

    Reads the raw reason strings (before redaction) and returns only a verdict
    — no date leaves this function.
    """
    if result is None:
        return None
    first_max = 0
    second_max = 0
    seen = 0
    separator = ""
    for entry in result.skipped:
        match = _DATE_TOKEN.search(str(entry.get("reason", "")))
        if not match:
            continue
        seen += 1
        separator = separator or match.group(2)
        first_max = max(first_max, int(match.group(1)))
        second_max = max(second_max, int(match.group(3)))
    if not seen:
        return None
    if first_max > 31:
        likely = "YYYY-MM-DD"
    elif first_max > 12:
        likely = "DD-MM-YYYY"
    elif second_max > 12:
        likely = "MM-DD-YYYY"
    else:
        likely = "ambiguous"
    return {"likely": likely, "separator": separator, "samples": seen}


# -------------------------------------------------------------- fingerprint


def fingerprint(
    platform: str,
    filename: str,
    data: bytes,
    result: ParseResult | None = None,
    validation: Validation | None = None,
    *,
    surface: str = "import",
    error: BaseException | None = None,
) -> dict:
    """The whole anonymised record of one import attempt."""
    out: dict = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform,
        "surface": surface,
        # The same pseudonymous slug the logs already carry (bound once per run
        # by stocks.web.telemetry), so three failures can be told apart as
        # three readers or as one reader retrying. Read off the obs context
        # rather than auth, which would drag Streamlit into this module.
        "user": obs.current().get("user", "-"),
        **sniff(filename, data),
        "imported": len(result.transactions) if result else 0,
        "skipped": len(result.skipped) if result else 0,
        "reasons": reasons(result),
    }
    hint = date_hint(result)
    if hint:
        out["date_hint"] = hint
    if validation is not None:
        out["rejected"] = len(validation.rejected)
        out["flagged"] = len(validation.flagged)
        out["issues"] = issue_counts(validation)
    if error is not None:
        out["error_type"] = type(error).__name__
        # The message can quote the offending bytes (UnicodeDecodeError does),
        # so it gets the same treatment as a skip reason.
        out["error"] = redact(str(error))[:300]
    return out


def failed(fp: dict) -> bool:
    """Whether this attempt is worth keeping a durable artifact for."""
    return bool(
        fp.get("error_type")
        or fp.get("skipped")
        or fp.get("rejected")
        or not fp.get("imported")
    )


# -------------------------------------------------------------------- sinks


def _fields(fp: dict) -> dict:
    """The fingerprint flattened for a log line — scalars and the top reason.

    The nested dicts stay out of Cloud Logging: they are what the durable
    artifact is for, and a log field per distinct reason string would make the
    index unqueryable.
    """
    flat = {k: v for k, v in fp.items() if not isinstance(v, (dict, list))}
    if fp.get("headers"):
        flat["columns"] = len(fp["headers"])
    if fp.get("reasons"):
        top, count = next(iter(fp["reasons"].items()))
        flat["top_reason"] = top
        flat["top_reason_rows"] = count
    if fp.get("issues"):
        flat["top_issue"] = next(iter(fp["issues"]))
    if fp.get("date_hint"):
        flat["date_hint"] = fp["date_hint"]["likely"]
    return flat


def record(fp: dict) -> Path | None:
    """Write the fingerprint to disk and the bucket; None if it couldn't be.

    Swallowed on purpose: losing the artifact must not also lose the import
    page, which is still rendering an error the reader needs to see.
    """
    try:
        DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = str(fp.get("ts", "")).replace(":", "-") or "unknown"
        path = DIAGNOSTICS_DIR / f"{stamp}-{uuid.uuid4().hex[:6]}.json"
        path.write_text(json.dumps(fp, ensure_ascii=False, indent=2))
        storage.persist(path)
        return path
    except Exception:  # noqa: BLE001
        obs.event("import.record_failed")
        return None


def report(
    platform: str,
    filename: str,
    data: bytes,
    result: ParseResult | None = None,
    validation: Validation | None = None,
    *,
    surface: str = "import",
    error: BaseException | None = None,
) -> dict:
    """Fingerprint one attempt, log it, and keep the failures.

    The single call every import surface makes. `user`, `session` and `page`
    are already bound by stocks.web.telemetry, so they need not be passed.
    """
    fp = fingerprint(
        platform, filename, data, result, validation,
        surface=surface, error=error,
    )
    broken = failed(fp)
    obs.event(
        "import.parse",
        level=logging.WARNING if broken else logging.INFO,
        ok=not broken,
        **_fields(fp),
    )
    if broken:
        path = record(fp)
        if path is not None:
            fp["id"] = path.stem
    return fp


# ---------------------------------------------------------------- read side


def stored(prefix: str = "data/imports/") -> list[dict]:
    """Every stored fingerprint, oldest first — local files plus bucket-only
    ones, so a fresh checkout sees production's."""
    items: dict[str, dict] = {}
    if DIAGNOSTICS_DIR.is_dir():
        for file in sorted(DIAGNOSTICS_DIR.glob("*.json")):
            try:
                items[file.name] = {**json.loads(file.read_text()), "id": file.stem}
            except (OSError, ValueError):
                continue
    for key in storage.list_keys(prefix):
        name = key.removeprefix(prefix)
        if name in items or not name.endswith(".json"):
            continue
        raw = storage.read_key(key)
        if not raw:
            continue
        try:
            items[name] = {**json.loads(raw), "id": name.removesuffix(".json")}
        except ValueError:
            continue
    return [items[k] for k in sorted(items)]


def find(diagnostic_id: str) -> dict | None:
    """One stored fingerprint by its id (the filename stem)."""
    for item in stored():
        if item.get("id") == diagnostic_id:
            return item
    return None


def recent(items: list[dict], hours: int = 24) -> list[dict]:
    """The fingerprints filed within the last `hours`.

    String comparison on the ISO stamp: the timestamps are written UTC and
    zero-padded by `fingerprint`, so lexical order is chronological order.
    """
    cutoff = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600)
    )
    return [i for i in items if str(i.get("ts", "")) >= cutoff]


def hotspots(items: list[dict], threshold: int = 3) -> list[dict]:
    """Platforms failing often enough to be worth a message, worst first.

    One broker breaking for one reader is noise; the same broker breaking for
    several is a parser bug with a queue of people behind it.
    """
    groups: dict[str, dict] = {}
    for item in items:
        key = str(item.get("platform", "?"))
        group = groups.setdefault(
            key, {"platform": key, "count": 0, "readers": set(), "reasons": {}}
        )
        group["count"] += 1
        group["readers"].add(str(item.get("user", "?")))
        for reason, n in (item.get("reasons") or {}).items():
            group["reasons"][reason] = group["reasons"].get(reason, 0) + n
        if item.get("error_type"):
            group["reasons"][item["error_type"]] = (
                group["reasons"].get(item["error_type"], 0) + 1
            )
    out = []
    for group in groups.values():
        if group["count"] < threshold:
            continue
        reasons_by_rows = sorted(
            group["reasons"].items(), key=lambda kv: kv[1], reverse=True
        )
        out.append({
            "platform": group["platform"],
            "count": group["count"],
            "readers": len(group["readers"]),
            "top_reason": reasons_by_rows[0][0] if reasons_by_rows else "",
        })
    return sorted(out, key=lambda g: g["count"], reverse=True)
