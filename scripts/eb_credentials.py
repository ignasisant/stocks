"""Write the Enable Banking application id and private key into
.streamlit/secrets.toml, without either ever passing through a shell
argument, the clipboard of another process, or this script's output.

    uv run python scripts/eb_credentials.py --id <application-id> --key path/to/key.pem

The id is not a secret (it travels in every JWT header as `kid`); the key is
the whole credential, so it is read straight from the file and never printed.
The file is rewritten in place with mode 600 and the previous contents kept
as secrets.toml.bak.<timestamp>.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".streamlit" / "secrets.toml"
BLOCK = re.compile(
    r'(\[enable_banking\]\n)(.*?)(?=\n\[|\Z)', re.DOTALL
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="application id from the control panel")
    ap.add_argument("--key", required=True, type=Path, help="path to the private key PEM")
    args = ap.parse_args()

    pem = args.key.read_bytes()
    try:
        serialization.load_pem_private_key(pem, password=None)
    except TypeError:
        print("That key is passphrase-protected; decrypt it first.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Not a usable private key PEM: {exc}", file=sys.stderr)
        return 1

    text = SECRETS.read_text()
    match = BLOCK.search(text)
    if not match:
        print("No [enable_banking] block in secrets.toml.", file=sys.stderr)
        return 1

    body = match.group(2)
    keep = [
        line for line in body.splitlines()
        if not line.startswith(("application_id", "private_key"))
        and '"""' not in line
        and "PRIVATE KEY" not in line
        and not re.fullmatch(r"[A-Za-z0-9+/=]{16,}", line.strip())
    ]
    while keep and not keep[-1].strip():
        keep.pop()

    rebuilt = (
        f'application_id = "{args.id}"\n'
        f'private_key = """\n{pem.decode().strip()}\n"""\n'
        + ("\n".join(keep) + "\n" if keep else "")
    )
    shutil.copy2(SECRETS, SECRETS.with_suffix(f".toml.bak.{int(time.time())}"))
    SECRETS.write_text(text[: match.start(2)] + rebuilt + text[match.end(2) :])
    SECRETS.chmod(0o600)
    print("secrets.toml updated. Now shred the key file:")
    print(f"  rm -P {args.key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
