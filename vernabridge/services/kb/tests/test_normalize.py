"""Tests for the import-time normalizer. All offline."""

from vb_kb.normalize import detect_script, normalize_name


def test_latin_names_are_casefolded_and_trimmed() -> None:
    assert normalize_name("  Sabiá   Laranjeira ") == "sabiá laranjeira"


def test_nfc_unifies_composed_and_decomposed_accents() -> None:
    # 'á' written as one character vs 'a' + combining accent must come out equal.
    composed = "sabiá"
    decomposed = "sabiá"
    assert normalize_name(composed) == normalize_name(decomposed)


def test_devanagari_is_not_casefolded() -> None:
    # Devanagari has no case; the name must pass through unchanged (minus spacing).
    assert normalize_name("महुआ") == "महुआ"


def test_normalization_is_idempotent() -> None:
    # Normalizing twice must equal normalizing once — for every script we handle.
    samples = ["  Quetzal  Mesoamericano ", "महुआ", "Árvore-do-viajante", "ñandú"]
    for raw in samples:
        once = normalize_name(raw)
        assert normalize_name(once) == once


def test_detect_script_latin() -> None:
    assert detect_script("sabiá laranjeira") == "Latn"


def test_detect_script_devanagari() -> None:
    assert detect_script("महुआ") == "Deva"


def test_detect_script_unknown_for_digits_only() -> None:
    assert detect_script("12345 !!") == "Zyyy"
