from usta.core.base import Frozen
from usta.core.model import Usage


class Price(Frozen):
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float


def cost_usd(usage: Usage, price: Price) -> float:
    return (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    ) / 1_000_000
