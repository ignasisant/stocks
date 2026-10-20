"""The assistant's drawer, end to end: open it, ask, read the streamed answer.

The model is scripted (`serve.CHAT_ANSWER`), so what is under test is the
transport a unit test cannot reach — the SSE stream through GZip and the
middleware stack, and the client assembling it into a turn.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.serve import CHAT_ANSWER

pytestmark = pytest.mark.e2e


def test_a_question_gets_its_streamed_answer(page: Page, sign_in):
    sign_in()
    page.goto("/home")
    page.get_by_role("button", name="Assistant", exact=True).click()
    drawer = page.get_by_role("dialog", name="Assistant")
    expect(drawer).to_be_visible()

    box = drawer.get_by_role("textbox")
    box.fill("¿Cómo va mi cartera?")
    box.press("Enter")

    expect(drawer).to_contain_text("¿Cómo va mi cartera?")
    # The first turn of a cold server builds the chat engine (prompt, memory,
    # knowledge index) before the fake provider answers; on a CI runner that
    # has run past the default 5 s (run 38386262098: "Thinking" still on
    # screen). The answer itself is instant, so the wait is on the engine.
    expect(drawer).to_contain_text(CHAT_ANSWER, timeout=20_000)


def test_a_guest_meets_the_assistant_locked(page: Page):
    """The real drawer spends the operator's keys and writes a history every
    anonymous visitor would share, so a guest gets the locked one (Locked.tsx):
    a sample exchange and the sign-in, no composer, and nothing sent to /chat."""
    chat_calls: list[str] = []
    page.on(
        "request",
        lambda request: (
            chat_calls.append(request.url) if "/api/v1/chat" in request.url else None
        ),
    )
    page.goto("/home")
    page.get_by_role("button", name="Assistant", exact=True).click()
    drawer = page.get_by_role("dialog", name="Assistant")
    expect(drawer).to_be_visible()

    expect(drawer).to_contain_text("Sign in and the AI reads your portfolio and answers.")
    expect(drawer.get_by_role("textbox")).to_have_count(0)
    page.wait_for_load_state("networkidle")
    assert chat_calls == []
