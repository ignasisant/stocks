"""What the chat's system prompt costs across a session, cached by part.

    uv run python scripts/bench_prompt_cache.py [--model claude-sonnet-5-5]

Replays a short session over one book — a question on Home, a follow-up, the
same thread from Portfolio, a question the router sends to other skills, a
turn after prices moved — and prices the system prompt's input tokens under
Anthropic's list prices (web/metering.py) two ways: one breakpoint on the
whole prompt (how it shipped before), and one per part (`llm.Prompt`: persona
with memories, book, the turn's own context). Counts are the engine's own
estimate (chat/tokens.py); the thread's turns are the same in both layouts
and left out. Offline: nothing is sent anywhere.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stocks.chat import engine, tokens  # noqa: E402
from stocks.web import metering  # noqa: E402

BOOK = (
    "Holdings (live market data, EUR). Total book 101,240 €, unrealised P/L "
    "+18,402 €:\n"
    + "\n".join(
        f"- {t}: {s:g} sh | value {v:,} € | cost {c:,} € | P/L {p:+.1%} "
        f"({v - c:+,} €) | weight {w:.0%} | today {d:+.1%}"
        for t, s, v, c, p, w, d in [
            ("NVDA", 40, 18400, 9200, 1.0, 0.18, 0.012),
            ("ASML", 12, 9100, 7800, 0.17, 0.09, -0.004),
            ("MELI", 5, 8900, 6100, 0.46, 0.09, 0.021),
            ("TSM", 60, 8200, 5900, 0.39, 0.08, 0.008),
            ("AMZN", 35, 7300, 5200, 0.4, 0.07, 0.003),
            ("MSFT", 15, 6900, 5400, 0.28, 0.07, -0.001),
            ("GOOGL", 30, 6100, 4800, 0.27, 0.06, 0.006),
            ("BABA", 50, 5200, 6100, -0.15, 0.05, 0.015),
            ("PDD", 30, 4100, 4400, -0.07, 0.04, -0.02),
            ("SE", 40, 3900, 3100, 0.26, 0.04, 0.009),
            ("ARM", 20, 3200, 2600, 0.23, 0.03, 0.03),
            ("CRWD", 8, 2900, 2200, 0.32, 0.03, 0.004),
            ("BTC-EUR", 0.12, 11200, 6800, 0.65, 0.11, 0.011),
            ("ETH-EUR", 1.5, 5840, 4200, 0.39, 0.06, 0.018),
        ]
    )
    + "\n\nSector exposure, funds looked through (share of the whole book / of "
    "its equity part): Technology 48.1% / 57.2%, Consumer Cyclical 22.0% / "
    "26.2%, Communication Services 6.0% / 7.2%; outside any equity sector: "
    "crypto 16.8%.\n\nAlso on the watchlist (not held): AMD, SHOP, CELH\n\n"
)
TAX = ("Tax residence: Spain. Gains are matched first in, first out; losses "
       "offset gains in the savings base, 25% of the remainder against "
       "dividends and interest.\n\n")
MEMORIES = ("What the user has told you to remember:\n- Prefers answers in "
            "euros.\n- Long horizon, five years at least; dislikes churn.\n- "
            "Treats crypto as a 15% sleeve, never more.\n\n")
VIEW_HOME = "Current view: Home.\n\n"
VIEW_PORTFOLIO = "Current view: Portfolio, Positions tab, looking at NVDA.\n\n"
PROFILE = {"set": True, "horizon": "long", "risk": "aggressive"}

# (label, view, skills, book) per turn.
SESSION = [
    ("Home, first question", VIEW_HOME, ["tech", "value"], BOOK),
    ("Home, follow-up", VIEW_HOME, ["tech", "value"], BOOK),
    ("moved to Portfolio", VIEW_PORTFOLIO, ["tech", "value"], BOOK),
    ("other skills", VIEW_PORTFOLIO, ["dividend", "portfolio-risk"], BOOK),
    ("prices moved", VIEW_PORTFOLIO, ["dividend", "portfolio-risk"],
     BOOK.replace("+18,402", "+18,655").replace("today +1.2%", "today +1.6%")),
]


def prompt(view: str, skills: list[str], book: str) -> engine.llm.Prompt:
    return engine.system_prompt(PROFILE, view, skills, "es",
                                memories=MEMORIES, book=book + TAX)


def bill(read: int, write: int, price: metering.Price) -> float:
    return (read * price.cached + write * price.cache_write) / 1_000_000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", default="claude-sonnet-5-5")
    args = ap.parse_args()
    price = metering.price(args.model)
    if price is None:
        raise SystemExit(f"{args.model} is unpriced in web/metering.py")

    prompts = [prompt(v, s, b) for _, v, s, b in SESSION]
    sizes = [tokens.count(p.blocks[0]), tokens.count(p.blocks[1]),
             tokens.count(p.blocks[2])] if (p := prompts[0]) else []
    print(f"system prompt: {sum(sizes)} tokens — persona+memories {sizes[0]}, "
          f"book {sizes[1]}, turn's own {sizes[2]} "
          f"({(sizes[0] + sizes[1]) / sum(sizes):.0%} stable)\n")
    print(f"{'turn':<22} {'whole: read/write':>18} {'parts: read/write':>18}"
          f" {'whole $':>9} {'parts $':>9}")
    whole_total = parts_total = 0.0
    prev: engine.llm.Prompt | None = None
    for (label, *_), cur in zip(SESSION, prompts, strict=True):
        n = tokens.count(cur)
        # One breakpoint: the whole prompt is a read only when byte-identical.
        w_read, w_write = (n, 0) if prev is not None and cur == prev else (0, n)
        # Per part: the longest run of parts equal to last turn's is read.
        p_read = 0
        if prev is not None:
            for a, b in zip(cur.blocks, prev.blocks, strict=False):
                if a != b:
                    break
                p_read += tokens.count(a)
        p_write = n - p_read
        w_usd, p_usd = bill(w_read, w_write, price), bill(p_read, p_write, price)
        whole_total += w_usd
        parts_total += p_usd
        print(f"{label:<22} {f'{w_read}/{w_write}':>18} {f'{p_read}/{p_write}':>18}"
              f" {w_usd:>9.5f} {p_usd:>9.5f}")
        prev = cur
    saving = 1 - parts_total / whole_total if whole_total else 0.0
    print(f"\n{'session':<22} {'':>18} {'':>18} {whole_total:>9.5f} {parts_total:>9.5f}"
          f"   ({saving:.0%} less on the system prompt)")


if __name__ == "__main__":
    main()
