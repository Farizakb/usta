"""Gateway: logging, retries, timeouts, circuit breaker and cost, outside the adapters
(ADR-020, P7). Every attempt is written to the audit sink, including failures."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping

from usta.core.audit import ModelCallRecord
from usta.core.errors import (
    ConfigError,
    ProviderQuotaError,
    ProviderRateLimited,
    ProviderUnavailable,
    TransientProviderError,
)
from usta.core.model import ModelRequest, ModelResponse, Role, Usage
from usta.models.pricing import Price, cost_usd
from usta.ports import AuditSink, ModelPort

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class CircuitBreaker:
    def __init__(self, threshold: int, reset_after_s: float, clock: Clock) -> None:
        self._threshold = threshold
        self._reset_after = reset_after_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    def check(self, provider: str) -> None:
        if self._opened_at is None:
            return
        if self._clock() - self._opened_at >= self._reset_after:
            self._opened_at = None
            self._failures = self._threshold - 1  # half-open: one more failure re-opens
            return
        raise ProviderUnavailable(
            f"{provider}: circuit open after {self._threshold} consecutive failures"
        )

    def success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()


class Gateway:
    def __init__(
        self,
        models: Mapping[Role, ModelPort],
        prices: Mapping[str, Price],
        audit: AuditSink,
        *,
        max_attempts: int = 3,
        base_delay_s: float = 1.0,
        timeout_s: float = 180.0,
        breaker_threshold: int = 5,
        breaker_reset_s: float = 60.0,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        missing = sorted({m.model_id for m in models.values()} - prices.keys())
        if missing:
            raise ConfigError(f"P7: no price entry for {missing}")
        self._models = dict(models)
        self._prices = dict(prices)
        self._audit = audit
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._timeout_s = timeout_s
        self._breaker_threshold = breaker_threshold
        self._breaker_reset_s = breaker_reset_s
        self._sleep = sleep
        self._clock = clock
        self._breakers: dict[str, CircuitBreaker] = {}

    async def complete(self, req: ModelRequest) -> ModelResponse:
        model = self._models[req.role]
        breaker = self._breakers.setdefault(
            model.provider,
            CircuitBreaker(self._breaker_threshold, self._breaker_reset_s, self._clock),
        )
        breaker.check(model.provider)
        last: TransientProviderError | None = None
        for attempt in range(1, self._max_attempts + 1):
            started = self._clock()
            try:
                resp = await asyncio.wait_for(model.complete(req), self._timeout_s)
            except TimeoutError:
                last = TransientProviderError(
                    f"{model.model_id}: no response within {self._timeout_s}s"
                )
            except TransientProviderError as e:
                last = e
            except Exception as e:  # ProviderError or a bug: log, then raise unchanged
                await self._log(req, model, attempt, started, error=e)
                raise
            else:
                cost = cost_usd(resp.usage, self._prices[model.model_id])
                resp = resp.model_copy(update={"cost_usd": cost})
                await self._log(req, model, attempt, started, resp=resp)
                breaker.success()
                return resp
            await self._log(req, model, attempt, started, error=last)
            breaker.failure()
            if attempt < self._max_attempts:
                await self._sleep(self._base_delay_s * 2 ** (attempt - 1))
        assert last is not None
        if isinstance(last, ProviderRateLimited):
            raise ProviderQuotaError(
                f"{model.model_id}: still rate limited after {self._max_attempts} attempts"
            ) from last
        raise last

    async def _log(
        self,
        req: ModelRequest,
        model: ModelPort,
        attempt: int,
        started: float,
        *,
        resp: ModelResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        await self._audit.model_call(
            ModelCallRecord(
                run_id=req.run_id,
                user_id=req.user_id,
                role=req.role,
                provider=model.provider,
                model=model.model_id,
                prompt_version=req.prompt_version,
                attempt=attempt,
                request=req.model_dump(mode="json"),
                response=resp.model_dump(mode="json") if resp else None,
                error=f"{type(error).__name__}: {error}" if error else None,
                usage=resp.usage if resp else Usage(),
                cost_usd=resp.cost_usd if resp else 0.0,
                latency_ms=int((self._clock() - started) * 1000),
            )
        )
