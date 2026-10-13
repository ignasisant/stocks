from stocks.formatting import bound, fmt_num, fmt_pct


def test_fmt_num_groups_four_digits_in_both_languages():
    assert fmt_num(9411, 0, "en") == "9,411"
    assert fmt_num(9411, 0, "es") == "9.411"
    assert fmt_num(1234.5, 2, "es") == "1.234,50"


def test_fmt_num_signed_and_pct():
    assert fmt_num(1.5, 1, "es", signed=True) == "+1,5"
    assert fmt_pct(0.0129, 1, "es") == "1,3%"
    assert fmt_pct(-0.05, 1, "en", signed=True) == "-5.0%"


def test_bound_applies_language():
    n, p = bound("es")
    assert n(27246, 0) == "27.246"
    assert p(0.5) == "50,0%"
