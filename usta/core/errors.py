class UstaError(Exception):
    """Expected, user-facing failure (printed without a traceback)."""


class ConfigError(UstaError):
    """Startup refused: profile, model catalog or environment is invalid."""


class ProviderError(UstaError):
    """Model provider failed; not retryable."""


class TransientProviderError(ProviderError):
    """Retryable: timeouts, 5xx, overload, connection errors."""


class ProviderRateLimited(TransientProviderError):
    """HTTP 429. Retried; still limited after all attempts -> ProviderQuotaError."""


class ProviderQuotaError(ProviderError):
    """Account quota or billing limit reached (stop_reason=provider_quota)."""


class ProviderUnavailable(ProviderError):
    """Circuit breaker is open for this provider."""


class UserBudgetExceeded(UstaError):
    """The user's monthly cost cap is reached; new runs are refused."""


class UnknownUser(UstaError):
    """A run was submitted for a user id that does not exist."""


class ToolInputError(UstaError):
    """Tool arguments are invalid; reported to the model as an error result."""
