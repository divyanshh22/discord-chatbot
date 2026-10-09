from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from typing import Any, Sequence

import aiohttp

from config import Config

log = logging.getLogger("controlroom.openrouter")


class OpenRouterError(Exception):
    pass


class BudgetExceeded(OpenRouterError):
    pass


class AuthenticationError(OpenRouterError):
    pass


class OpenRouterClient:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._session: aiohttp.ClientSession | None = None
        self._daily_count = 0
        self._day = _dt.date.today()

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._config.request_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def _roll_day(self) -> None:
        today = _dt.date.today()
        if today != self._day:
            self._day = today
            self._daily_count = 0

    @property
    def requests_today(self) -> int:
        self._roll_day()
        return self._daily_count

    @property
    def budget_remaining(self) -> int:
        self._roll_day()
        return max(0, self._config.daily_request_budget - self._daily_count)

    def budget_available(self) -> bool:
        return self.budget_remaining > 0

    def _headers(self, api_key: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": self._config.openrouter_app_name,
        }
        if self._config.openrouter_app_url:
            headers["HTTP-Referer"] = self._config.openrouter_app_url
        return headers

    def _attempts(self) -> list[tuple[str, str, str]]:
        """Ordered (base_url, api_key, model) attempts across providers."""
        attempts: list[tuple[str, str, str]] = []
        primary_models = [
            self._config.openrouter_model,
            *self._config.openrouter_fallback_models,
        ]
        for model in primary_models:
            if model:
                attempts.append(
                    (
                        self._config.openrouter_base_url,
                        self._config.openrouter_api_key,
                        model,
                    )
                )
        if self._config.secondary_configured:
            for model in self._config.openrouter_secondary_models:
                if model:
                    attempts.append(
                        (
                            self._config.openrouter_secondary_base_url,
                            self._config.openrouter_secondary_api_key,
                            model,
                        )
                    )
        return attempts

    async def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.budget_available():
            raise BudgetExceeded(
                "Daily OpenRouter request budget reached; skipping AI request."
            )

        attempts = self._attempts()
        if not attempts:
            raise OpenRouterError("No AI model or provider is configured.")

        await self.start()
        assert self._session is not None

        payload: dict[str, Any] = {
            "messages": list(messages),
            "temperature": (
                self._config.temperature if temperature is None else temperature
            ),
            "max_tokens": (
                self._config.max_tokens if max_tokens is None else max_tokens
            ),
            "reasoning": {"enabled": False},
        }

        last_error: Exception | None = None
        total = len(attempts)
        for index, (base_url, api_key, model) in enumerate(attempts):
            has_fallback = index + 1 < total
            if not api_key:
                last_error = OpenRouterError(
                    "API key is not configured for the selected provider."
                )
                continue

            url = f"{base_url.rstrip('/')}/chat/completions"
            try:
                return await self._request_model(
                    url,
                    self._headers(api_key),
                    payload,
                    model,
                    has_fallback=has_fallback,
                )
            except AuthenticationError as exc:
                last_error = exc
                if not has_fallback:
                    raise
                log.warning(
                    "Auth failed for model %s (%s); trying next provider/model.",
                    model,
                    exc,
                )
            except OpenRouterError as exc:
                last_error = exc
                if not has_fallback:
                    break
                log.warning(
                    "Model %s failed (%s); trying next provider/model.",
                    model,
                    exc,
                )

        raise last_error or OpenRouterError("OpenRouter request failed.")

    async def _request_model(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        model: str,
        has_fallback: bool = False,
    ) -> str:
        assert self._session is not None
        body = {**payload, "model": model}
        body_without_reasoning = {
            key: value for key, value in body.items() if key != "reasoning"
        }
        reasoning_stripped = False

        attempt = 0
        max_attempts = self._config.max_retries + 1
        last_error: Exception | None = None

        while attempt < max_attempts:
            attempt += 1
            try:
                async with self._session.post(
                    url, json=body, headers=headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = self._extract_content(data)
                        if content:
                            self._daily_count += 1
                            return content
                        last_error = OpenRouterError(
                            "Empty completion from model."
                        )
                        log.warning(
                            "Model %s returned empty content; trying fallback.",
                            model,
                        )
                        break

                    raw = await _safe_text(resp)

                    if (
                        resp.status == 400
                        and not reasoning_stripped
                        and "reasoning" in raw.lower()
                    ):
                        reasoning_stripped = True
                        body = dict(body_without_reasoning)
                        body["max_tokens"] = max(
                            int(body.get("max_tokens", 160)), 800
                        )
                        attempt -= 1
                        log.warning(
                            "Model %s requires reasoning; retrying without the "
                            "reasoning flag.",
                            model,
                        )
                        continue

                    if resp.status == 429:
                        retry_after = _retry_after(resp)
                        last_error = OpenRouterError("Rate limited (429).")
                        log.warning(
                            "OpenRouter rate limited; backing off %.1fs (attempt %d/%d) for model %s.",
                            retry_after,
                            attempt,
                            max_attempts,
                            model,
                        )
                        if attempt < max_attempts:
                            await asyncio.sleep(retry_after)
                            continue
                        if has_fallback:
                            raise last_error
                        break

                    if 500 <= resp.status < 600:
                        last_error = OpenRouterError(
                            f"OpenRouter server error ({resp.status})."
                        )
                        log.warning(
                            "OpenRouter server error %s (attempt %d/%d).",
                            resp.status,
                            attempt,
                            max_attempts,
                        )
                        if attempt < max_attempts:
                            await asyncio.sleep(_backoff(attempt))
                            continue
                        break

                    if resp.status in (401, 403):
                        log.error(
                            "OpenRouter authentication failed (%s). "
                            "Check OPENROUTER_API_KEY.",
                            resp.status,
                        )
                        raise AuthenticationError(
                            "Authentication failed; verify OPENROUTER_API_KEY."
                        )

                    if resp.status == 404:
                        last_error = OpenRouterError(
                            "Model not found; check OPENROUTER_MODEL and "
                            "OPENROUTER_BASE_URL."
                        )
                        log.warning(
                            "OpenRouter model %s not found (404).", model
                        )
                        break

                    log.error(
                        "OpenRouter request failed with status %s: %s",
                        resp.status,
                        raw,
                    )
                    last_error = OpenRouterError(
                        f"OpenRouter request failed ({resp.status})."
                    )
                    break

            except asyncio.TimeoutError:
                last_error = OpenRouterError("OpenRouter request timed out.")
                log.warning(
                    "OpenRouter timeout (attempt %d/%d).", attempt, max_attempts
                )
                if attempt < max_attempts:
                    await asyncio.sleep(_backoff(attempt))
                    continue
                break
            except aiohttp.ClientError as exc:
                last_error = OpenRouterError(f"Network error: {exc.__class__.__name__}")
                log.warning(
                    "OpenRouter network error %s (attempt %d/%d).",
                    exc.__class__.__name__,
                    attempt,
                    max_attempts,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(_backoff(attempt))
                    continue
                break
            except OpenRouterError:
                raise
            except Exception as exc:
                last_error = OpenRouterError(
                    f"Unexpected error: {exc.__class__.__name__}"
                )
                log.exception("Unexpected OpenRouter error.")
                break

        raise last_error or OpenRouterError("OpenRouter request failed.")

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            raise OpenRouterError("OpenRouter returned no choices.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )
        if not content or not str(content).strip():
            return ""
        return str(content).strip()


def _backoff(attempt: int) -> float:
    return min(1.5 * (2 ** (attempt - 1)), 8.0)


def _retry_after(resp: aiohttp.ClientResponse) -> float:
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return max(0.5, min(float(raw), 15.0))
        except ValueError:
            pass
    return 2.0


async def _safe_text(resp: aiohttp.ClientResponse) -> str:
    try:
        text = await resp.text()
    except Exception:
        return ""
    return text[:500]
