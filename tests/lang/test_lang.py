import pytest

from usta.lang import MIN_WORDS, LangResult, az_casefold, detect, langcheck

AZ = (
    "Keçən həftə şirkətimizin bütün avtomobilləri üçün yanacaq sərfiyyatı hesabatı hazırlandı "
    "və nəticələr iclasda müzakirə olunacaq, xüsusilə Bakı filialında artım müşahidə edildi."
)
TR = (
    "Geçen hafta şirketimizin bütün araçları için yakıt tüketimi raporu hazırlandı ve sonuçlar "
    "toplantıda tartışılacak, özellikle İstanbul şubesinde belirgin bir artış gözlendi."
)
EN = (
    "Last week the fuel consumption report for all of our company vehicles was prepared and the "
    "results will be discussed at the meeting, especially the increase seen in the Baku branch."
)
RU = (
    "На прошлой неделе был подготовлен отчёт о расходе топлива для всех автомобилей нашей "
    "компании, и результаты будут обсуждаться на совещании, особенно рост в бакинском филиале."
)


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("İSTİQAMƏT", "istiqamət"),
        ("IŞIQ", "ışıq"),
        ("İstanbul", "istanbul"),
        ("Gəncə", "gəncə"),
        ("ÇÖÜĞ", "çöüğ"),
        ("ı", "ı"),
    ],
)
def test_az_casefold_pitfall_words(text: str, folded: str) -> None:
    assert az_casefold(text) == folded


def test_str_lower_is_wrong_and_az_casefold_is_not() -> None:
    assert "İSTİQAMƏT".lower() != "istiqamət"  # F5: Python inserts U+0307 and maps I→i
    assert az_casefold("IŞIQ") != "IŞIQ".lower()


@pytest.mark.parametrize(("text", "code"), [(AZ, "az"), (TR, "tr"), (EN, "en"), (RU, "ru")])
def test_detect_four_languages(text: str, code: str) -> None:
    assert len(text.split()) >= MIN_WORDS
    assert detect(text) == code


def test_detect_skips_short_text_unless_asked() -> None:
    assert detect("Hesabatı hazırla") is None
    assert detect("Hesabatı hazırla", min_words=1) == "az"  # ə rule


def test_schwa_means_azerbaijani() -> None:
    assert detect("ə " * 20) == "az"


def test_langcheck_pass_fail_and_skip() -> None:
    assert langcheck(AZ, "az") == LangResult(ok=True, detected="az", reason=None)
    bad = langcheck(TR, "az")
    assert not bad.ok and bad.detected == "tr" and "expected az" in (bad.reason or "")
    short = langcheck("Bəli.", "az")
    assert short.ok and short.detected is None and "skipped" in (short.reason or "")


def test_azerbaijani_without_schwa_is_suspicious() -> None:
    text = "bu gün biz ofisdə deyilik " * 4  # no ə would reach the detector in real drift
    result = langcheck(text.replace("ə", "e"), "az", detect_fn=lambda t, **_: "az")
    assert not result.ok and "without ə" in (result.reason or "")
