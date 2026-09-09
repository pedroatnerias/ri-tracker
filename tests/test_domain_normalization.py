from domain_normalization import coerce_number, normalize_text, repair_mojibake


def test_shared_normalization_repairs_mojibake_and_strips_accents():
    assert normalize_text("LanÃ§amentos") == "lancamentos"


def test_shared_repair_leaves_regular_text_unchanged():
    assert repair_mojibake("Construção civil") == "Construção civil"


def test_shared_normalization_can_preserve_accents_for_display_matching():
    assert normalize_text("Construção civil", strip_accents=False) == "construção civil"


def test_coerce_number_handles_json_and_brazilian_values():
    assert coerce_number("1.234,56") == 1234.56
    assert coerce_number("1234.56") == 1234.56
    assert coerce_number(float("nan")) is None
    assert coerce_number(True) is None
