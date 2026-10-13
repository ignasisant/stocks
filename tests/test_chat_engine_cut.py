from stocks.chat.engine import close_markdown


def test_closes_open_fence():
    assert close_markdown("```py\nx = 1") .endswith("\n```")


def test_drops_dangling_link_and_pairs_bold():
    assert close_markdown("see [the repo](https://exa") == "see"
    assert close_markdown("a **bold") == "a **bold**"


def test_drops_unfinished_table_row():
    assert close_markdown("| a | b |\n|---|---|\n| 1 | 2") == "| a | b |\n|---|---|"


def test_complete_text_untouched():
    assert close_markdown("All **fine**.") == "All **fine**."
