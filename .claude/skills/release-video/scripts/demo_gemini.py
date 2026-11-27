"""
Store a Gemini API key as the demo account's own key (BYOK), typed without echo.

Run from the app repo: `uv run python demo_gemini.py video-demo@example.com`. The key never
appears on screen, in argv or in a log; it is stored encrypted the way the app stores any
user's key (needs `[chat] enc_key`). Free providers rate-limit in bursts; a demo take needs an
answer in seconds, so record the AI scenes on the demo's own key with a fast model.
"""

import getpass
import json
import sys

from stocks import accounts
from stocks.chat.engine.providers import save_byok

FAST_MODEL = 'gemini-flash-lite-latest'  # flash-latest / 3.x flash time out when busy


def main() -> None:
    """
    Prompt for the key and save it on the demo account.

    :return: None
    """
    email = sys.argv[1].strip().lower()
    if not email.endswith('@example.com'):
        sys.exit('only @example.com demo accounts')
    prefs = accounts.paths_for(email).prefs
    key = getpass.getpass('Pega la clave de Gemini (no se ve) y pulsa Enter: ').strip()
    if not key:
        sys.exit('vacía, nada guardado')
    d = json.loads(prefs.read_text()) if prefs.exists() else {}
    if not save_byok(d, 'gemini', key):
        sys.exit('FALLO: falta [chat] enc_key')
    d['llm_provider'] = 'gemini'
    d['gemini_model'] = FAST_MODEL
    prefs.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    print('guardada')


if __name__ == '__main__':
    main()
