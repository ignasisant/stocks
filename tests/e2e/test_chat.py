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
    expect(drawer).to_contain_text(CHAT_ANSWER)


def test_a_guest_is_not_offered_the_assistant(page: Page):
    """It spends the operator's keys and writes a history every anonymous
    visitor would share (Layout.tsx) — so it is not there to click."""
    page.goto("/home")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("button", name="Assistant", exact=True)).to_have_count(0)
