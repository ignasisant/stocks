"""Connect a bank account (PSD2 account information, via Enable Banking).

Read-only: balances and, later, the transfers that move money between this
bank account and a broker — the external cash flows the ledger cannot see.
Nothing here initiates a payment.

The page is also the OAuth-style landing spot. Its url_path is "bank", so the
redirect URL registered with Enable Banking is <host>/bank and the bank sends
the user back here with ?code=&state=. That return is a fresh browser session:
the `state` is matched against bank.json (see stocks.bank.store), never against
session state, which no longer exists by then.
"""

from __future__ import annotations

import streamlit as st

from stocks.bank import enablebanking, store
from stocks.bank.enablebanking import BankError, ConsentError, RateLimited
from stocks.web import auth, bank_ui
from stocks.web.i18n import t as tr

# Bank data is as personal as it gets — login first, always.
auth.require_login()

st.title(tr("bank.title"))

if not bank_ui.available():
    st.info(tr("bank.unavailable"), icon=":material/lock:")
    st.stop()

paths = auth.user_paths()
email = auth.current_email()

# Countries Enable Banking covers that this app is likely to be used from;
# the ASPSP list itself comes from the API per country.
COUNTRIES = (
    "ES", "PT", "FR", "IT", "DE", "NL", "BE", "IE",
    "FI", "SE", "NO", "DK", "AT", "PL",
)

@st.cache_data(ttl=3600, show_spinner=False)
def _aspsps(country: str) -> list[dict]:
    """Banks for a country. Cached: the list is reference data, identical for
    every user, and refetching it on each rerun would burn the rate limit."""
    return enablebanking.aspsps(country)


def _balance_text(balances: list[dict]) -> str:
    """The account's balance as a line of text. Which of the bank's balances
    that is lives in `store`, so the shell shows the same one."""
    money = store.balance_money(balances)
    if money is None:
        return "—"
    amount, currency = money
    return f"{amount:,.2f} {currency}".strip()


# ------------------------------------------------------- redirect landing
# Handled before anything is drawn: the code is single-use and short-lived.
_params = st.query_params
_code = (_params.get("code") or "").strip()
_state = (_params.get("state") or "").strip()
_error = (_params.get("error") or "").strip()

if _error:
    st.warning(tr("bank.auth_declined"), icon=":material/block:")
    st.query_params.clear()
elif _code and _state:
    pending = store.take_pending(paths.bank, _state, email)
    if pending is None:
        # Unknown, expired or another account's state: the code may be real,
        # but nothing proves this session started the round trip.
        st.error(tr("bank.state_mismatch"), icon=":material/error:")
        st.query_params.clear()
    else:
        try:
            session = enablebanking.create_session(_code)
        except BankError as exc:
            st.error(tr("bank.connect_failed", detail=exc.description or exc.code))
            st.query_params.clear()
        else:
            conn = store.add_connection(paths.bank, session, aspsp=pending["aspsp"])
            st.query_params.clear()
            # The "continue to your bank" link belongs to a round trip that
            # has now finished; leaving it would offer a spent auth URL.
            st.session_state.pop("bank_auth_url", None)
            st.session_state["bank_just_connected"] = conn["aspsp"]["name"]
            st.rerun()

if _name := st.session_state.pop("bank_just_connected", ""):
    st.toast(tr("bank.connected_toast", bank=_name), icon=":material/account_balance:")

st.caption(tr("bank.intro_caption"))

# ---------------------------------------------------------- connected banks
_connections = store.connections(paths.bank)

for conn in _connections:
    session_id = conn.get("session_id", "")
    bank_name = conn.get("aspsp", {}).get("name", "—")
    gone = store.expired(conn)
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{bank_name}** · {conn.get('aspsp', {}).get('country', '')}")
            if gone:
                st.badge(tr("bank.consent_expired"), color="orange")
            else:
                st.caption(
                    tr("bank.valid_until", date=(conn.get("valid_until") or "")[:10])
                )
        for acc in conn.get("accounts", []):
            snapshot = acc.get("snapshot") or {}
            label = " · ".join(
                p for p in (acc.get("name"), acc.get("masked_id")) if p
            ) or acc.get("uid", "")
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(label)
                st.markdown(f"**{_balance_text(snapshot.get('balances') or [])}**")
            if snapshot.get("fetched_at"):
                st.caption(
                    tr("bank.fetched_at", when=snapshot["fetched_at"].replace("T", " "))
                )
        with st.container(horizontal=True, vertical_alignment="center"):
            if st.button(
                tr("bank.refresh"),
                key=f"refresh_{session_id}",
                icon=":material/refresh:",
                disabled=gone,
            ):
                try:
                    for acc in conn.get("accounts", []):
                        store.record_fetch(
                            paths.bank,
                            session_id,
                            acc["uid"],
                            balances=enablebanking.balances(acc["uid"]),
                        )
                except RateLimited:
                    # The bank's daily budget, not an error of ours: four
                    # fetches a day is the common ceiling. Nothing to fix.
                    st.warning(tr("bank.rate_limited"), icon=":material/hourglass:")
                except ConsentError:
                    # The consent died before its stated date (revoked at the
                    # bank, or the ASPSP cut it short) — mark it so the card
                    # offers a reconnect instead of a button that can't work.
                    store.mark_expired(paths.bank, session_id)
                    st.warning(tr("bank.consent_gone"), icon=":material/link_off:")
                except BankError as exc:
                    st.error(
                        tr("bank.refresh_failed", detail=exc.description or exc.code)
                    )
                else:
                    st.rerun()
            with st.popover(tr("bank.disconnect"), icon=":material/link_off:"):
                st.markdown(tr("bank.disconnect_confirm", bank=bank_name))
                if st.button(
                    tr("bank.disconnect_confirm_button"),
                    key=f"disconnect_{session_id}",
                    type="primary",
                    icon=":material/link_off:",
                ):
                    try:
                        enablebanking.delete_session(session_id)
                    except BankError:
                        # Local state is what the UI shows; a session left
                        # open at the bank expires on its own and the user
                        # asked for it gone here.
                        pass
                    store.remove_connection(paths.bank, session_id)
                    st.rerun()

if not _connections:
    st.info(tr("bank.none_connected"), icon=":material/account_balance:")

# ------------------------------------------------------------ add a bank
st.subheader(tr("bank.add_title"))

_country = st.selectbox(
    tr("bank.country"), COUNTRIES, index=0, key="bank_country"
)

try:
    _banks = _aspsps(_country)
except BankError as exc:
    st.error(tr("bank.aspsps_failed", detail=exc.description or exc.code))
    _banks = []

if _banks:
    # Options are names, not the ASPSP dicts: the selection round-trips
    # through session state, and a plain string is what survives that.
    _by_name = {a.get("name", ""): a for a in _banks}
    _chosen = _by_name[
        st.selectbox(tr("bank.bank"), sorted(_by_name), key=f"bank_pick_{_country}")
    ]
    _redirect = bank_ui.redirect_url()
    if not _redirect:
        st.warning(tr("bank.no_redirect"), icon=":material/warning:")
    elif st.button(
        tr("bank.connect"),
        type="primary",
        icon=":material/account_balance:",
        disabled=not _redirect,
    ):
        try:
            url, state = enablebanking.start_auth(
                name=_chosen["name"],
                country=_country,
                redirect_url=_redirect,
            )
        except BankError as exc:
            st.error(tr("bank.connect_failed", detail=exc.description or exc.code))
        else:
            store.add_pending(
                paths.bank, state=state, email=email, aspsp=_chosen
            )
            st.session_state["bank_auth_url"] = url
            st.session_state["bank_auth_name"] = _chosen["name"]
            st.rerun()

if _url := st.session_state.get("bank_auth_url", ""):
    st.link_button(
        tr("bank.continue_to_bank", bank=st.session_state.get("bank_auth_name", "")),
        _url,
        type="primary",
        icon=":material/open_in_new:",
    )
    st.caption(tr("bank.continue_caption"))

st.caption(tr("bank.privacy_caption"))
