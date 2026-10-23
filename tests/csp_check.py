"""One assertion for every server-rendered HTML document: its CSP is real.

Parses the markup (not a regex) and holds the response to the policy it ships
with: no `'unsafe-inline'`, no `style=""` attribute, no `on*=` handler, and
every inline `<style>` / executable `<script>` hashed in the header.
"""

from __future__ import annotations

from html.parser import HTMLParser

from stocks.web import csp


class _Scan(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []
        self.blocks: list[tuple[str, str]] = []
        self._open: tuple[str, str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        names = {k.lower(): (v or "") for k, v in attrs}
        for name in names:
            if name == "style" or name.startswith("on"):
                self.problems.append(f"<{tag} {name}=…> is inline")
        if tag == "style":
            self._open = ("style", "")
        elif tag == "script" and "src" not in names and not names.get(
            "type", ""
        ).startswith("application/"):
            self._open = ("script", "")
        else:
            self._open = None
        self._text = []

    def handle_data(self, data):
        self._text.append(data)

    def handle_endtag(self, tag):
        if self._open and self._open[0] == tag:
            self.blocks.append((tag, "".join(self._text)))
        self._open = None
        self._text = []


def assert_enforced(response) -> None:
    policy = response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in policy, policy
    assert "'unsafe-eval'" not in policy, policy
    for directive in ("default-src", "object-src 'none'", "base-uri",
                      "frame-ancestors 'none'", "form-action"):
        assert directive in policy, (directive, policy)
    scan = _Scan()
    scan.feed(response.text)
    assert not scan.problems, scan.problems
    for tag, body in scan.blocks:
        assert csp.source(body) in policy, f"inline <{tag}> not in the policy"
