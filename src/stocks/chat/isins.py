"""ISINs in an answer, checked against the registry before it is stored.

A model writes an ISIN from memory as readily as a ticker, and an ISIN is
twelve characters nobody can check by eye. A bond-ETF answer in prod
(2026-11-02) gave eight: three failed the check digit, one was a BTP OpenFIGI
has never heard of, and three were real but other funds — "€ Govt Bond
1-3yr" was iShares Core MSCI World. Printed bare, the reader had no way to
tell.

So each ISIN-shaped word is settled before the answer is kept:

- a wrong check digit, or one OpenFIGI says it has no record of, is made up
  and comes out of the text;
- one OpenFIGI knows is written bold, which the chat panel draws as a ticker
  cell with the security's own name beside it (`chat/markdown.tsx`), so a
  label that does not match it shows;
- one nobody could ask about (OpenFIGI throttled or down) is left as written,
  and so is one the reader typed: "that ISIN does not exist" has to name it.
"""

from __future__ import annotations

import re

from stocks import obs
from stocks.data import openfigi

_ISIN = r"[A-Z]{2}[A-Z0-9]{9}[0-9]"
# Bold, in backticks or bare: whatever wraps it goes with it.
_WORD = re.compile(rf"\*\*({_ISIN})\*\*|`({_ISIN})`|(?<![\w*`])({_ISIN})(?![\w*`])")

# What taking one out leaves behind: "(, IE00…)", "( )", " ,".
_EMPTY_PARENS = re.compile(r"\(\s*[,;/]?\s*\)")
_LEADING_SEP = re.compile(r"\(\s*[,;/]\s*")
_DOUBLE_SEP = re.compile(r"([,;])\s*[,;]")
_SPACE_BEFORE = re.compile(r"[ \t]+([,;.:)])")
_SPACES = re.compile(r"(?<=\S)[ \t]{2,}")


def check_digit_ok(isin: str) -> bool:
    """ISO 6166: letters to two digits each (A=10), then Luhn over the lot."""
    digits = "".join(str(int(c, 36)) for c in isin[:-1])
    total = 0
    for n, ch in enumerate(reversed(digits)):
        d = int(ch)
        if n % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(isin[-1])


def _tidy(line: str) -> str:
    line = _EMPTY_PARENS.sub("", line)
    line = _LEADING_SEP.sub("(", line)
    line = _DOUBLE_SEP.sub(r"\1", line)
    line = _SPACE_BEFORE.sub(r"\1", line)
    return _SPACES.sub(" ", line).rstrip()


def found(text: str) -> set[str]:
    """Every ISIN-shaped word in `text`, bold, in backticks or bare."""
    return {m.group(1) or m.group(2) or m.group(3) for m in _WORD.finditer(text)}


def settle(words: set[str]) -> tuple[set[str], dict[str, openfigi.Security]]:
    """`words` split into the made up and the known, with what each one is.

    What is in neither was not settled: OpenFIGI could not be asked.
    """
    sane = [isin for isin in words if check_digit_ok(isin)]
    known = openfigi.securities(sane) if sane else {}
    made_up = {isin for isin in words if isin not in known}
    made_up |= {
        isin for isin, sec in known.items() if sec is None and openfigi.missed(isin)
    }
    return made_up, {isin: sec for isin, sec in known.items() if sec is not None}


def verify(text: str, asked: str = "") -> str:
    """`text` with every made-up ISIN taken out and every known one bold.

    An ISIN in `asked` (what the reader typed) is never taken out: an answer
    saying it does not exist has to name it.
    Never raises: OpenFIGI failing leaves the ISINs as the model wrote them.
    """
    words = found(text)
    if not words:
        return text
    made_up, real = settle(words)
    made_up -= found(asked)

    def one(match: re.Match) -> str:
        isin = match.group(1) or match.group(2) or match.group(3)
        if isin in made_up:
            return ""
        if isin in real:
            return f"**{isin}**"
        return match.group(0)

    out = []
    for line in text.split("\n"):
        fixed = _WORD.sub(one, line)
        if any(isin in line for isin in made_up):
            indent = line[: len(line) - len(line.lstrip())]
            fixed = indent + _tidy(fixed).lstrip()
        out.append(fixed)
    obs.event("chat.isins", seen=len(words), made_up=len(made_up), known=len(real))
    return "\n".join(out)
