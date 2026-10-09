import pytest

from usta.core.errors import (
    ProviderError,
    ProviderQuotaError,
    ProviderRateLimited,
    TransientProviderError,
)
from usta.models.errors import map_status
from usta.models.toolnames import decode, encode


def test_dots_are_encoded_for_the_wire_and_decoded_back() -> None:
    assert encode("file.read") == "file__read"
    assert decode("file__read") == "file.read"
    assert decode(encode("fleet.fuel_report")) == "fleet.fuel_report"


def test_names_with_double_underscore_are_refused() -> None:
    with pytest.raises(ValueError):
        encode("bad__name")


@pytest.mark.parametrize("name", ["a_.b", "a._b", "_.b", "a._", "x._.y"])
def test_underscore_adjacent_to_dot_is_refused(name: str) -> None:
    # "a_.b" would encode to "a___b", which decodes to "a._b" (not round-trip safe).
    with pytest.raises(ValueError):
        encode(name)


@pytest.mark.parametrize(
    "name",
    ["fleet.fuel_report", "file.read", "a_b.c", "a.b_c", "a..b", "snake_case", "_private", "plain"],
)
def test_accepted_names_round_trip(name: str) -> None:
    assert decode(encode(name)) == name


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (402, ProviderQuotaError),
        (429, ProviderRateLimited),
        (408, TransientProviderError),
        (409, TransientProviderError),
        (500, TransientProviderError),
        (529, TransientProviderError),
        (400, ProviderError),
        (401, ProviderError),
        (None, ProviderError),
    ],
)
def test_map_status(status: int | None, error: type) -> None:
    assert type(map_status(status, "boom")) is error
