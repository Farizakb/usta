"""Map provider HTTP status codes to Usta errors. Shared by adapters, so it is not an adapter."""

from usta.core.errors import (
    ProviderError,
    ProviderQuotaError,
    ProviderRateLimited,
    TransientProviderError,
)


def map_status(status: int | None, message: str) -> ProviderError:
    if status == 402:
        return ProviderQuotaError(message)
    if status == 429:
        return ProviderRateLimited(message)
    if status in (408, 409) or (status is not None and status >= 500):
        return TransientProviderError(message)
    return ProviderError(message)
