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

__all__ = ['API_URL_USAGE', 'API_URL_PROFILE', 'CLAUDE_CONFIG_DIR', 'CLAUDE_CREDENTIALS', 'read_access_token', 'api_headers', 'fetch_usage', 'fetch_profile']

# API endpoints & credentials
API_URL_USAGE = 'https://api.anthropic.com/api/oauth/usage'
API_URL_PROFILE = 'https://api.anthropic.com/api/oauth/profile'
CLAUDE_CONFIG_DIR = Path(os.environ.get('CLAUDE_CONFIG_DIR', '')) if os.environ.get('CLAUDE_CONFIG_DIR') else Path.home() / '.claude'
CLAUDE_CREDENTIALS = CLAUDE_CONFIG_DIR / '.credentials.json'
_FALLBACK_USER_AGENT = 'claude-code/2.1.85'

# macOS Keychain item identifiers used by Claude Code.
# v2.1.52+ uses a hashed suffix; earlier versions used the plain name.
_KEYCHAIN_SERVICE_LEGACY = 'Claude Code-credentials'
_KEYCHAIN_SERVICE_PREFIX = 'Claude Code-credentials-'
_SECURITY_BIN = '/usr/bin/security'
_resolved_keychain_service: str | None = None


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
        return creds.get('claudeAiOauth', {}).get('accessToken') or None
    except (json.JSONDecodeError, KeyError):
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
        return resp.json()
    except requests.ConnectionError:
        return {'error': T['connection_error']}
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        server_msg = _extract_server_message(e.response)
        extra: dict[str, Any] = {}
        if server_msg:
            extra['server_message'] = server_msg

        if code == 401:
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


def _macos_keychain_service_candidates() -> list[str]:
    """Return the Keychain service names to probe, most-likely first.

    Claude Code v2.1.52+ uses a hashed suffix (``Claude Code-credentials-<HASH>``);
    earlier versions used the plain legacy name. The hashed name is discovered
    once per process via ``security dump-keychain`` and then cached in memory.
    """
    global _resolved_keychain_service
    if _resolved_keychain_service is not None:
        return [_resolved_keychain_service, _KEYCHAIN_SERVICE_LEGACY]

    hashed = _find_macos_hashed_keychain_service()
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
