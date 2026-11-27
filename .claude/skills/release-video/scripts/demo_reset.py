"""
Reset the throwaway demo account before a take, inside the app's own environment.

Run from the app repo with `uv run python demo_reset.py <demo_email> [--probe]` (the recorder
does this for every `record` on an environment with `demo_email`). It:

- gives the chat one real, empty thread. An absent or empty chat.json makes the app invent a
  new random thread id on every read, so the drawer sends to a thread the server never
  listed and the turn fails with `chat.api_error` (POST /chat/runs 404);
- gives every held name exit rules and a thesis, so the Diario reads as a book in use, not an
  empty state (`seed_rules`; stops sit ~25 % under the price: a stop further than 1.5x away is flagged 'drift' (Toca revisar));
- closes the chat drawer (`chat_panel_open: false`) so every take starts on the bare page;
- with `--probe`, asks the AI the demo question once and reports how long it took, so a slow
  or failing provider is found before a take, not in the clip.

Only `@example.com` accounts: never the owner, never a real user.
"""

import sys
import time

from stocks import accounts
from stocks.chat import conversations

GUARD = '@example.com'


def main() -> None:
    """
    Reset the demo account named on the command line.

    :return: None
    """
    email = sys.argv[1].strip().lower()
    if not email.endswith(GUARD):
        sys.exit(f'demo_reset: {email} is not a {GUARD} demo account')
    paths = accounts.paths_for(email)
    paths.root.mkdir(parents=True, exist_ok=True)
    conversations.save_book(conversations._empty_book(), paths.chat)
    conversations.new_conversation(paths.chat)
    seed_rules(paths)
    if paths.prefs.exists():
        accounts.update_prefs(paths.prefs, {'chat_panel_open': False})
    print(f'demo_reset: {paths.root.name} chat cleared, drawer closed')
    if '--probe' in sys.argv:
        probe(paths)


RULES = {
    'AAPL': (270, 'Servicios y recompra sostienen el margen'),
    'MSFT': (370, 'Azure sigue creciendo por encima del 25 %'),
    'TSLA': (300, 'Margen automotriz estable y energía creciendo'),
    'GOOGL': (205, 'Search resiste y Cloud gana margen'),
    'NVDA': (112, 'Los hiperescaladores siguen subiendo el capex en IA'),
    'META': (470, 'Publicidad crece con inversión en IA controlada'),
    'NOW': (70, 'Renovaciones por encima del 98 % y alza de precios'),
}


def seed_rules(paths) -> None:
    """
    Give each held name a price stop, a drawdown stop and a thesis rule (idempotent).

    :param paths: accounts.UserPaths, demo account paths
    :return: None
    """
    from datetime import date

    from stocks.chat import journal

    for code, (stop, thesis) in RULES.items():
        journal.add_criteria(
            paths.journal,
            code,
            [
                {'rule': 'below', 'level': stop},
                {'rule': 'drawdown_high', 'level': 40},
                {'rule': 'thesis', 'pillars': [thesis]},
            ],
            date.today(),
            thesis,
        )


def probe(paths) -> None:
    """
    Ask the AI one demo question and report the time and provider error, if any.

    :param paths: accounts.UserPaths, demo account paths
    :return: None
    """
    from stocks.chat import engine

    question = sys.argv[sys.argv.index('--probe') + 1] if len(sys.argv) > sys.argv.index('--probe') + 1 else (
        '¿Qué posición debería vigilar más y por qué?'
    )
    t = time.time()
    r = engine.answer(
        prefs=accounts.load_prefs(paths.prefs),
        prefs_path=paths.prefs,
        chat_path=paths.chat,
        watchlist=paths.watchlist,
        db=paths.db,
        message=question,
        lang='es',
        timeout_s=120,
    )
    secs = round(time.time() - t, 1)
    print(f'demo_reset: probe {secs}s error={r.error}')
    print((getattr(r, 'text', '') or '')[:600])
    # The probe's turn must not be on camera: start the take on a clean thread again.
    conversations.save_book(conversations._empty_book(), paths.chat)
    conversations.new_conversation(paths.chat)
    if r.error or secs > 40:
        sys.exit(f'demo_reset: AI too slow or failing ({secs}s, {r.error}); fix the provider before recording')


if __name__ == '__main__':
    main()
