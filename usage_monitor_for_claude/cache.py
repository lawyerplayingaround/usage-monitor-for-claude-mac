"""
Usage Cache
============

Thread-safe cache for API data - single source of truth for all usage
state.  All API refresh requests go through ``UsageCache.update()``,
which uses a lock to prevent concurrent calls and a cooldown to prevent
calls that are too close together (HTTP 429).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from .api import fetch_profile, fetch_usage, read_access_token
from .claude_cli import RefreshResult, refresh_token
from .settings import MAX_BACKOFF, POLL_FAST, POLL_INTERVAL

__all__ = ['CacheSnapshot', 'UpdateResult', 'UsageCache']


@dataclass(frozen=True)
class CacheSnapshot:
    """Immutable, consistent snapshot of cache state for the popup."""

    usage: dict[str, Any]
    profile: dict[str, Any] | None
    last_success_time: float | None
    refreshing: bool
    last_error: str | None
    version: int


@dataclass(frozen=True)
class UpdateResult:
    """Result of a ``UsageCache.update()`` call.

    Attributes
    ----------
    data : dict or None
        Raw API response dict, or ``None`` when the call was skipped
        (lock held or cooldown active).
    token_refresh : RefreshResult or None
        Set when a token refresh was attempted after a 401 auth error.
    """

    data: dict[str, Any] | None
    token_refresh: RefreshResult | None = None


class UsageCache:
    """Thread-safe cache managing API data, cooldown, and error state.

    All callers (poll loop, popup, manual refresh) go through
    ``update()`` instead of calling ``fetch_usage()`` directly.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._profile_lock = threading.Lock()
        self._usage: dict[str, Any] = {}
        self._profile: dict[str, Any] | None = None
        self._last_success_time: float | None = None
        self._refreshing = False
        self._last_error: str | None = None
        self._version = 0
        self._consecutive_errors = 0
        self._last_failed_token: str | None = None
        self._rate_limit_until: float = 0

    # ── Public properties ─────────────────────────────────────

    @property
    def usage(self) -> dict[str, Any]:
        """Last successful usage data (empty dict before first success)."""
        return self._usage

    @property
    def profile(self) -> dict[str, Any] | None:
        return self._profile

    @property
    def last_success_time(self) -> float | None:
        return self._last_success_time

    @property
    def refreshing(self) -> bool:
        return self._refreshing

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def version(self) -> int:
        """Change counter - incremented on every state change."""
        return self._version

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    @property
    def rate_limit_remaining(self) -> float:
        """Seconds remaining in the rate-limit backoff window, or 0."""
        return max(self._rate_limit_until - time.time(), 0)

    @property
    def snapshot(self) -> CacheSnapshot:
        """Return a consistent snapshot for the popup to display."""
        with self._state_lock:
            return CacheSnapshot(
                usage=self._usage,
                profile=self._profile,
                last_success_time=self._last_success_time,
                refreshing=self._refreshing,
                last_error=self._last_error,
                version=self._version,
            )

    # ── Public methods ────────────────────────────────────────

    def clear_failed_token(self) -> None:
        """Reset the failed-token guard so the next update retries the API."""
        self._last_failed_token = None

    def ensure_profile(self) -> None:
        """Fetch the account profile if not yet loaded (thread-safe).

        Acquires ``_lock`` around the HTTP call to prevent concurrent
        API requests with ``update()``.
        """
        if self._profile is not None:
            return

        with self._profile_lock:
            if self._profile is not None:
                return
            with self._lock:
                profile = fetch_profile()
            with self._state_lock:
                self._profile = profile

    def update(self, *, force: bool = False) -> UpdateResult:
        """Fetch usage data with lock and cooldown protection.

        Parameters
        ----------
        force : bool
            Bypass the cooldown (e.g. for explicit user refresh).

        Returns
        -------
        UpdateResult
            Contains the API response dict (``data``), or ``None``
            when the call was skipped.  If a token refresh was
            attempted, ``token_refresh`` carries the outcome.
        """
        if not self._lock.acquire(blocking=force):
            return UpdateResult(data=None)

        try:
            return self._update_locked(force=force)
        finally:
            self._lock.release()

    # ── Private helpers ───────────────────────────────────────

    def _update_locked(self, *, force: bool = False) -> UpdateResult:
        """Execute the actual update while holding ``_lock``."""
        if not force and self._last_success_time is not None and time.time() - self._last_success_time < POLL_FAST:
            return UpdateResult(data=None)

        if not force and time.time() < self._rate_limit_until:
            return UpdateResult(data=None)

        if not force and self._last_failed_token is not None:
            if read_access_token() == self._last_failed_token:
                return UpdateResult(data=None)
            self._last_failed_token = None

        with self._state_lock:
            self._refreshing = True
            self._version += 1

        try:
            return self._fetch_and_process()
        except Exception:
            with self._state_lock:
                self._refreshing = False
                self._version += 1
            raise

    def _fetch_and_process(self) -> UpdateResult:
        """Fetch usage data and process the response."""
        token_before = read_access_token()
        data = fetch_usage()

        if 'error' in data:
            self._record_error(data)

            if data.get('rate_limited'):
                retry_after = data.get('retry_after')
                if retry_after is not None and retry_after > 0:
                    delay = min(max(retry_after, POLL_INTERVAL), MAX_BACKOFF)
                else:
                    delay = min(POLL_INTERVAL * (2 ** max(self._consecutive_errors - 1, 0)), MAX_BACKOFF)
                self._rate_limit_until = time.time() + delay

            token_refresh = None
            if data.get('auth_error'):
                token_refresh = self._try_token_refresh(token_before)
                if token_refresh is not None and self._last_error is None:
                    # Token refresh succeeded and retry was successful
                    return UpdateResult(data=self._usage, token_refresh=token_refresh)
                if token_refresh is None:
                    # Refresh failed or token unchanged - block this token
                    self._last_failed_token = token_before

            with self._state_lock:
                self._refreshing = False
                self._version += 1
            return UpdateResult(data=data, token_refresh=token_refresh)

        self._record_success(data)
        return UpdateResult(data=data)

    def _record_error(self, data: dict[str, Any]) -> None:
        """Apply common state updates after a failed API response."""
        with self._state_lock:
            self._consecutive_errors += 1
            self._last_error = data['error']
            server_msg = data.get('server_message')
            if server_msg:
                self._last_error += f'\n{server_msg}'

    def _record_success(self, data: dict[str, Any]) -> None:
        """Apply common state updates after a successful API response."""
        # _usage is always reassigned (never mutated in place), so existing
        # CacheSnapshot references remain valid after this update.
        with self._state_lock:
            self._consecutive_errors = 0
            self._last_error = None
            self._last_success_time = time.time()
            self._rate_limit_until = 0
            self._last_failed_token = None
            self._usage = data
            self._refreshing = False
            self._version += 1

    def _try_token_refresh(self, token_before: str | None) -> RefreshResult | None:
        """Attempt to refresh the OAuth token via ``claude update``.

        Parameters
        ----------
        token_before : str or None
            The token that was used for the failed request.  Used to
            detect whether the refresh actually produced a new token.

        Returns
        -------
        RefreshResult or None
            The refresh outcome, or ``None`` if the CLI is not available
            or the token didn't change.
        """
        result = refresh_token()
        if not result.success:
            return None

        if read_access_token() == token_before:
            return None

        # Token changed - retry the API call
        data = fetch_usage()
        if 'error' not in data:
            self._record_success(data)
            return result

        # Retry failed - update error message with retry details
        # but do not increment _consecutive_errors again (the caller
        # already counted this update cycle as one error).
        with self._state_lock:
            self._last_error = data['error']
            server_msg = data.get('server_message')
            if server_msg:
                self._last_error += f'\n{server_msg}'

        return result
