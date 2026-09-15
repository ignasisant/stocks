"""Bank account access (PSD2 AIS) through the Enable Banking API.

`enablebanking` is the HTTP client (stdlib urllib, JWT signed locally with
`cryptography` — no SDK, same shape as notify/telegram.py); `store` keeps one
account's consent state next to the rest of its data.
"""
