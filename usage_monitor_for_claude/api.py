"""
API Client
===========

Reads Claude Code OAuth credentials and communicates with the
Anthropic API.  This is the only module that handles credentials.

Network communication exclusively with ``api.anthropic.com``.
Credentials used only in HTTP Authorization headers.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests

from .i18n import T
from .preferences import get_show_fable_separately

__all__ = ['API_URL_USAGE', 'API_URL_PROFILE', 'CLAUDE_CONFIG_DIR', 'CLAUDE_CREDENTIALS', 'read_access_token', 'api_headers', 'fetch_usage', 'fetch_profile']

# API endpoints & credentials
API_URL_USAGE = 'https://api.anthropic.com/api/oauth/usage'
API_URL_PROFILE = 'https://api.anthropic.com/api/oauth/profile'
CLAUDE_CONFIG_DIR = Path(os.environ.get('CLAUDE_CONFIG_DIR', '')) if os.environ.get('CLAUDE_CONFIG_DIR') else Path.home() / '.claude'
CLAUDE_CREDENTIALS = CLAUDE_CONFIG_DIR / '.credentials.json'
_FALLBACK_USER_AGENT = 'claude-code/2.1.204'

# macOS Keychain item identifiers used by Claude Code.
# v2.1.52+ uses a hashed suffix; earlier versions used the plain name.
_KEYCHAIN_SERVICE_LEGACY = 'Claude Code-credentials'
_KEYCHAIN_SERVICE_PREFIX = 'Claude Code-credentials-'
_SECURITY_BIN = '/usr/bin/security'
_resolved_keychain_service: str | None = None
_keychain_discovery_done: bool = False


def read_access_token() -> str | None:
    """Read the current access token from the Claude credentials store.

    On macOS, Claude Code persists credentials in the system Keychain.
    On other platforms, credentials live in ``CLAUDE_CREDENTIALS`` as JSON.
    The token is never cached in memory beyond the duration of the caller.
    """
    if sys.platform == 'darwin':
        return _read_access_token_macos()

    if not CLAUDE_CREDENTIALS.exists():
        return None

    try:
        creds = json.loads(CLAUDE_CREDENTIALS.read_text())
        oauth = creds.get('claudeAiOauth') if isinstance(creds, dict) else None
        return oauth.get('accessToken') or None if isinstance(oauth, dict) else None
    except (OSError, ValueError):
        # OSError also covers a read racing a concurrent write (the file is
        # rewritten on token rotation/account switch); treat it as "no token
        # right now" rather than letting it crash a caller.
        return None


def api_headers() -> dict[str, str] | None:
    """Return auth headers for the Anthropic OAuth API, or None."""
    token = read_access_token()
    if not token:
        return None

    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'User-Agent': _user_agent(),
        'anthropic-beta': 'oauth-2025-04-20',
    }


def fetch_usage() -> dict[str, Any]:
    """Fetch usage data from the Anthropic OAuth usage API."""
    headers = api_headers()
    if not headers:
        return {'error': T['no_token']}

    try:
        resp = requests.get(API_URL_USAGE, headers=headers, timeout=10)
        resp.raise_for_status()
        return _merge_scoped_limits(resp.json())
    except requests.ConnectionError:
        return {'error': T['connection_error']}
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        server_msg = _extract_server_message(e.response)
        extra: dict[str, Any] = {}
        if server_msg:
            extra['server_message'] = server_msg

        if code == 401:
            # An expired or revoked token can happen when the user logs
            # into a different Claude Code account or v2.1.52+ rotates
            # the hashed Keychain service name.  Clear the cached macOS
            # service name so the next read_access_token() call re-runs
            # the discovery and picks up the fresh entry.
            _invalidate_keychain_cache()
            return {**extra, 'error': T['auth_expired'], 'auth_error': True}
        if code == 429:
            retry = _parse_retry_after(e.response)
            if retry is not None:
                extra['retry_after'] = retry
            return {**extra, 'error': T['http_error'].format(code=429), 'rate_limited': True}
        if 500 <= code < 600:
            return {**extra, 'error': T['server_error'].format(code=code)}
        return {**extra, 'error': T['http_error'].format(code=code or '?')}
    except Exception:
        return {'error': T['connection_error']}


def fetch_profile() -> dict[str, Any] | None:
    """Fetch account profile from the Anthropic OAuth profile API."""
    headers = api_headers()
    if not headers:
        return None

    try:
        resp = requests.get(API_URL_PROFILE, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


# Helpers


def _merge_scoped_limits(data: dict[str, Any]) -> dict[str, Any]:
    """Expose model-scoped limits from the ``limits`` array as quota fields.

    Newer usage responses carry per-model weekly limits only inside the
    ``limits`` array (via ``scope.model``), no longer as top-level fields
    like ``seven_day_sonnet``.  To keep them visible without hardcoding any
    field name, each active scoped limit is mapped onto a synthetic quota
    field that the existing field-name auto-detection understands.

    The period prefix is derived from the response, not assumed: the
    non-scoped limit of the same ``group`` shares its ``resets_at`` with an
    existing top-level quota field, whose name supplies the prefix (e.g. a
    weekly limit scoped to Fable becomes ``seven_day_fable``).  Inactive
    scoped limits (no reset window) are still surfaced at 0% so the model's
    limit is visible before it is first used; an existing top-level field is
    never overwritten (it carries higher-precision data).

    Parameters
    ----------
    data : dict
        Raw usage API response.

    Returns
    -------
    dict
        The response with synthetic quota fields added for any model-scoped
        limits not already present as top-level fields.
    """
    limits = data.get('limits')
    if not isinstance(limits, list):
        return data

    # resets_at -> existing top-level quota field name (the prefix source)
    reset_to_field: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, dict) and value.get('utilization') is not None:
            resets_at = value.get('resets_at')
            if resets_at:
                reset_to_field.setdefault(resets_at, key)

    # group -> period prefix, via the non-scoped limit's shared reset time
    group_prefix: dict[str, str] = {}
    for limit in limits:
        if not isinstance(limit, dict) or limit.get('scope'):
            continue
        group = limit.get('group')
        resets_at = limit.get('resets_at')
        if group and resets_at and resets_at in reset_to_field:
            group_prefix.setdefault(group, reset_to_field[resets_at])

    merged = dict(data)
    for limit in limits:
        if not isinstance(limit, dict):
            continue
        model = (limit.get('scope') or {}).get('model') or {}
        display_name = model.get('display_name')
        prefix = group_prefix.get(limit.get('group'))
        if not display_name or not prefix:
            continue

        slug = _model_slug(display_name)
        # Fable is credit-based rather than quota-based for most accounts, so
        # its scoped weekly limit can be hidden via the menu toggle.
        if slug == 'fable' and not get_show_fable_separately():
            continue

        field = f'{prefix}_{slug}'
        if merged.get(field) is not None:
            continue
        merged[field] = {'utilization': float(limit.get('percent') or 0), 'resets_at': limit.get('resets_at')}

    return merged


def _model_slug(display_name: str) -> str:
    """Convert a model display name into a field-name suffix (e.g. ``'Fable'`` -> ``'fable'``)."""
    cleaned = ''.join(char if char.isalnum() else ' ' for char in display_name.lower())
    return '_'.join(cleaned.split())


def _user_agent() -> str:
    """Return the User-Agent string with the installed Claude Code version."""
    from .claude_cli import CLAUDE_CLI_PATH, cli_version

    version = cli_version(CLAUDE_CLI_PATH)
    return f'claude-code/{version}' if version else _FALLBACK_USER_AGENT


def _extract_server_message(response: requests.Response | None) -> str | None:
    """Extract ``error.message`` from a JSON error response body.

    Strips the trailing "Please try again later." suffix that the API
    appends to some error messages - the app retries automatically, so
    the advice would be misleading.
    """
    if response is None:
        return None
    try:
        msg = response.json().get('error', {}).get('message') or None
        if msg:
            msg = msg.removesuffix(' Please try again later.').removesuffix(' Please try again later').strip()
        return msg or None
    except Exception:
        return None


def _parse_retry_after(response: requests.Response | None) -> int | None:
    """Parse the ``Retry-After`` header as an integer number of seconds."""
    if response is None:
        return None
    raw = response.headers.get('Retry-After')
    if raw is None:
        return None
    try:
        return max(int(raw), 0)
    except (ValueError, TypeError):
        return None


# macOS Keychain helpers (only invoked when sys.platform == 'darwin')


def _read_access_token_macos() -> str | None:
    """Read the access token from the macOS Keychain item written by Claude Code."""
    for service in _macos_keychain_service_candidates():
        token = _read_macos_keychain_token(service)
        if token is not None:
            return token
    return None


def _invalidate_keychain_cache() -> None:
    """Clear the cached Keychain service name so the next read re-discovers it.

    Called when the Anthropic API returns 401 - typically because the
    user has signed into a different Claude Code account and v2.1.52+
    rotated the hashed service name we resolved earlier.  No-op on
    non-darwin platforms (the cache is only populated there).
    """
    global _resolved_keychain_service, _keychain_discovery_done
    _resolved_keychain_service = None
    _keychain_discovery_done = False


def _macos_keychain_service_candidates() -> list[str]:
    """Return the Keychain service names to probe, most-likely first.

    Claude Code v2.1.52+ uses a hashed suffix (``Claude Code-credentials-<HASH>``);
    earlier versions used the plain legacy name. The hashed name is discovered
    once per process via ``security dump-keychain``; both a positive result (the
    resolved name) and a negative one (no hashed entry exists) are cached, so the
    expensive keychain dump runs at most once per process rather than on every
    token read. ``_invalidate_keychain_cache`` resets both on an HTTP 401.
    """
    global _resolved_keychain_service, _keychain_discovery_done
    if _resolved_keychain_service is not None:
        return [_resolved_keychain_service, _KEYCHAIN_SERVICE_LEGACY]
    if _keychain_discovery_done:
        return [_KEYCHAIN_SERVICE_LEGACY]

    hashed = _find_macos_hashed_keychain_service()
    _keychain_discovery_done = True
    if hashed:
        _resolved_keychain_service = hashed
        return [hashed, _KEYCHAIN_SERVICE_LEGACY]

    return [_KEYCHAIN_SERVICE_LEGACY]


def _find_macos_hashed_keychain_service() -> str | None:
    """Search the login keychain for a service name with the v2.1.52+ hashed suffix."""
    try:
        result = subprocess.run(
            [_SECURITY_BIN, 'dump-keychain'],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None

    marker = '="'
    for line in result.stdout.splitlines():
        if '"svce"' not in line or _KEYCHAIN_SERVICE_PREFIX not in line:
            continue
        start = line.find(marker)
        if start < 0:
            continue
        end = line.find('"', start + len(marker))
        if end < 0:
            continue
        name = line[start + len(marker):end]
        if name.startswith(_KEYCHAIN_SERVICE_PREFIX):
            return name
    return None


def _read_macos_keychain_token(service: str) -> str | None:
    """Read and parse the OAuth JSON blob stored under ``service`` in the Keychain."""
    try:
        result = subprocess.run(
            [_SECURITY_BIN, 'find-generic-password', '-s', service, '-w'],
            capture_output=True, text=True, timeout=3,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None

    raw = result.stdout.strip()
    if not raw:
        return None
    try:
        creds = json.loads(raw)
        return creds.get('claudeAiOauth', {}).get('accessToken') or None
    except (json.JSONDecodeError, KeyError):
        return None
