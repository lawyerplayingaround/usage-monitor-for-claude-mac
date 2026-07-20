"""
API Client Tests
=================

Unit tests for read_access_token() and fetch_usage().
"""
from __future__ import annotations

import json
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import MagicMock, patch

from usage_monitor_for_claude.api import (
    API_URL_USAGE, _extract_server_message, _merge_scoped_limits, _model_slug, _parse_retry_after, fetch_usage, read_access_token,
)
from usage_monitor_for_claude.i18n import LOCALE_DIR

_IS_DARWIN = sys.platform == 'darwin'
_FILE_BASED_SKIP_REASON = 'file-based credentials path is not used on macOS (Keychain is used instead)'

EN = json.loads((LOCALE_DIR / 'en.json').read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# CLAUDE_CONFIG_DIR
# ---------------------------------------------------------------------------

class TestClaudeConfigDir(unittest.TestCase):
    """Tests for CLAUDE_CONFIG_DIR resolution."""

    def test_default_uses_home_claude(self):
        """Without CLAUDE_CONFIG_DIR env var, defaults to ~/.claude/."""
        with patch.dict('os.environ', {}, clear=False):
            # Remove CLAUDE_CONFIG_DIR if it happens to be set
            env = {k: v for k, v in __import__('os').environ.items() if k != 'CLAUDE_CONFIG_DIR'}
            with patch.dict('os.environ', env, clear=True):
                import importlib
                import usage_monitor_for_claude.api as api_mod
                importlib.reload(api_mod)
                try:
                    self.assertEqual(api_mod.CLAUDE_CONFIG_DIR, Path.home() / '.claude')
                    self.assertEqual(api_mod.CLAUDE_CREDENTIALS, Path.home() / '.claude' / '.credentials.json')
                finally:
                    importlib.reload(api_mod)

    def test_custom_config_dir(self):
        """CLAUDE_CONFIG_DIR env var overrides the default path."""
        with TemporaryDirectory() as tmp:
            with patch.dict('os.environ', {'CLAUDE_CONFIG_DIR': tmp}):
                import importlib
                import usage_monitor_for_claude.api as api_mod
                importlib.reload(api_mod)
                try:
                    self.assertEqual(api_mod.CLAUDE_CONFIG_DIR, Path(tmp))
                    self.assertEqual(api_mod.CLAUDE_CREDENTIALS, Path(tmp) / '.credentials.json')
                finally:
                    importlib.reload(api_mod)

    def test_empty_config_dir_uses_default(self):
        """Empty CLAUDE_CONFIG_DIR env var falls back to default."""
        with patch.dict('os.environ', {'CLAUDE_CONFIG_DIR': ''}):
            import importlib
            import usage_monitor_for_claude.api as api_mod
            importlib.reload(api_mod)
            try:
                self.assertEqual(api_mod.CLAUDE_CONFIG_DIR, Path.home() / '.claude')
            finally:
                importlib.reload(api_mod)


# ---------------------------------------------------------------------------
# read_access_token
# ---------------------------------------------------------------------------

@unittest.skipIf(_IS_DARWIN, _FILE_BASED_SKIP_REASON)
class TestReadAccessToken(unittest.TestCase):
    """Tests for read_access_token() on platforms that use the credentials file."""

    def test_file_missing(self):
        """Missing credentials file returns None."""
        with TemporaryDirectory() as tmp:
            fake_path = Path(tmp) / 'nonexistent.json'
            with patch('usage_monitor_for_claude.api.CLAUDE_CREDENTIALS', fake_path):
                self.assertIsNone(read_access_token())

    def test_valid_token(self):
        """Extracts token from well-formed credentials file."""
        creds = {'claudeAiOauth': {'accessToken': 'sk-test-123'}}
        with TemporaryDirectory() as tmp:
            creds_file = Path(tmp) / 'creds.json'
            creds_file.write_text(json.dumps(creds))
            with patch('usage_monitor_for_claude.api.CLAUDE_CREDENTIALS', creds_file):
                self.assertEqual(read_access_token(), 'sk-test-123')

    def test_malformed_json(self):
        """Malformed JSON returns None."""
        with TemporaryDirectory() as tmp:
            creds_file = Path(tmp) / 'creds.json'
            creds_file.write_text('not json')
            with patch('usage_monitor_for_claude.api.CLAUDE_CREDENTIALS', creds_file):
                self.assertIsNone(read_access_token())

    def test_missing_oauth_key(self):
        """Missing claudeAiOauth key returns None."""
        with TemporaryDirectory() as tmp:
            creds_file = Path(tmp) / 'creds.json'
            creds_file.write_text('{"otherKey": {}}')
            with patch('usage_monitor_for_claude.api.CLAUDE_CREDENTIALS', creds_file):
                self.assertIsNone(read_access_token())

    def test_missing_access_token_key(self):
        """Missing accessToken key returns None."""
        creds = {'claudeAiOauth': {'refreshToken': 'rt-123'}}
        with TemporaryDirectory() as tmp:
            creds_file = Path(tmp) / 'creds.json'
            creds_file.write_text(json.dumps(creds))
            with patch('usage_monitor_for_claude.api.CLAUDE_CREDENTIALS', creds_file):
                self.assertIsNone(read_access_token())

    def test_empty_token_string(self):
        """Empty token string returns None (falsy check)."""
        creds = {'claudeAiOauth': {'accessToken': ''}}
        with TemporaryDirectory() as tmp:
            creds_file = Path(tmp) / 'creds.json'
            creds_file.write_text(json.dumps(creds))
            with patch('usage_monitor_for_claude.api.CLAUDE_CREDENTIALS', creds_file):
                self.assertIsNone(read_access_token())

    def test_read_error_returns_none(self):
        """An OS-level read failure (e.g. a read racing a concurrent write) returns None instead of raising."""
        with TemporaryDirectory() as tmp:
            creds_file = Path(tmp) / 'creds.json'
            creds_file.write_text('{"claudeAiOauth": {"accessToken": "sk-test-123"}}')
            with patch('usage_monitor_for_claude.api.CLAUDE_CREDENTIALS', creds_file), \
                 patch.object(Path, 'read_text', side_effect=PermissionError('locked')):
                self.assertIsNone(read_access_token())

    def test_null_oauth_value_returns_none(self):
        """A claudeAiOauth key holding JSON null (e.g. after a logout) returns None instead of raising."""
        with TemporaryDirectory() as tmp:
            creds_file = Path(tmp) / 'creds.json'
            creds_file.write_text('{"claudeAiOauth": null}')
            with patch('usage_monitor_for_claude.api.CLAUDE_CREDENTIALS', creds_file):
                self.assertIsNone(read_access_token())

    def test_non_object_top_level_returns_none(self):
        """Valid JSON with a non-object top level (list, string, number) returns None instead of raising."""
        for content in ('[]', '"token"', '42', 'null'):
            with self.subTest(content=content), TemporaryDirectory() as tmp:
                creds_file = Path(tmp) / 'creds.json'
                creds_file.write_text(content)
                with patch('usage_monitor_for_claude.api.CLAUDE_CREDENTIALS', creds_file):
                    self.assertIsNone(read_access_token())

    def test_non_dict_oauth_value_returns_none(self):
        """A claudeAiOauth key holding a non-object value returns None instead of raising."""
        with TemporaryDirectory() as tmp:
            creds_file = Path(tmp) / 'creds.json'
            creds_file.write_text('{"claudeAiOauth": "sk-test-123"}')
            with patch('usage_monitor_for_claude.api.CLAUDE_CREDENTIALS', creds_file):
                self.assertIsNone(read_access_token())


# ---------------------------------------------------------------------------
# fetch_usage
# ---------------------------------------------------------------------------

@patch('usage_monitor_for_claude.api.T', EN)
class TestFetchUsage(unittest.TestCase):
    """Tests for fetch_usage()."""

    @patch('usage_monitor_for_claude.api.api_headers', return_value=None)
    def test_no_token_returns_error(self, _mock_headers):
        """Missing token returns no_token error."""
        result = fetch_usage()
        self.assertEqual(result, {'error': EN['no_token']})

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_success(self, _mock_headers, mock_get):
        """Successful response returns parsed JSON."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'five_hour': {'utilization': 42.0}}
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertEqual(result, {'five_hour': {'utilization': 42.0}})
        mock_get.assert_called_once_with(API_URL_USAGE, headers={'Authorization': 'Bearer test'}, timeout=10)

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_connection_error(self, _mock_headers, mock_get):
        """ConnectionError returns connection_error message."""
        import requests
        mock_get.side_effect = requests.ConnectionError()

        result = fetch_usage()

        self.assertEqual(result, {'error': EN['connection_error']})

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_401_returns_auth_error(self, _mock_headers, mock_get):
        """HTTP 401 returns auth_error with flag."""
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertEqual(result['error'], EN['auth_expired'])
        self.assertTrue(result['auth_error'])

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_401_invalidates_keychain_cache(self, _mock_headers, mock_get):
        """A 401 from the API clears the cached macOS Keychain service name."""
        import requests
        import usage_monitor_for_claude.api as api_mod

        # Seed the cache as if discovery had run successfully.
        api_mod._resolved_keychain_service = 'Claude Code-credentials-DEADBEEF'

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        fetch_usage()

        self.assertIsNone(api_mod._resolved_keychain_service)

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_server_error_500(self, _mock_headers, mock_get):
        """HTTP 500 returns server_error with status code."""
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertEqual(result, {'error': EN['server_error'].format(code=500)})

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_server_error_503(self, _mock_headers, mock_get):
        """HTTP 503 returns server_error with status code."""
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertEqual(result, {'error': EN['server_error'].format(code=503)})

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_client_http_error(self, _mock_headers, mock_get):
        """Non-5xx, non-401 HTTP error returns http_error with status code."""
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertEqual(result, {'error': EN['http_error'].format(code=403)})

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_http_error_without_response(self, _mock_headers, mock_get):
        """HTTPError with response=None uses '?' as status code."""
        import requests
        mock_get.side_effect = requests.HTTPError(response=None)

        result = fetch_usage()

        self.assertEqual(result, {'error': EN['http_error'].format(code='?')})
        self.assertNotIn('auth_error', result)

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_generic_exception(self, _mock_headers, mock_get):
        """Unexpected exception returns connection_error message."""
        mock_get.side_effect = RuntimeError('unexpected')

        result = fetch_usage()

        self.assertEqual(result, {'error': EN['connection_error']})

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_only_calls_usage_url(self, _mock_headers, mock_get):
        """Verify the request goes exclusively to API_URL_USAGE."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp

        fetch_usage()

        called_url = mock_get.call_args[0][0]
        self.assertEqual(called_url, 'https://api.anthropic.com/api/oauth/usage')


# ---------------------------------------------------------------------------
# 429 / rate limit handling
# ---------------------------------------------------------------------------

@patch('usage_monitor_for_claude.api.T', EN)
class TestFetchUsageRateLimit(unittest.TestCase):
    """Tests for HTTP 429 rate-limit handling in fetch_usage()."""

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_429_returns_rate_limited_flag(self, _mock_headers, mock_get):
        """HTTP 429 sets rate_limited flag."""
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {}
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertTrue(result['rate_limited'])
        self.assertEqual(result['error'], EN['http_error'].format(code=429))

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_429_with_retry_after(self, _mock_headers, mock_get):
        """HTTP 429 with Retry-After header includes retry_after in result."""
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {'Retry-After': '60'}
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertEqual(result['retry_after'], 60)
        self.assertTrue(result['rate_limited'])

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_429_with_server_message(self, _mock_headers, mock_get):
        """HTTP 429 with JSON error body includes server_message."""
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {'Retry-After': '0'}
        mock_resp.json.return_value = {'error': {'message': 'Rate limited. Please try again later.'}}
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertEqual(result['server_message'], 'Rate limited.')

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_429_without_retry_after_header(self, _mock_headers, mock_get):
        """HTTP 429 without Retry-After header omits retry_after from result."""
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {}
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertNotIn('retry_after', result)

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_server_message_on_non_429_error(self, _mock_headers, mock_get):
        """Server message is included for non-429 HTTP errors too."""
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {'error': {'message': 'Internal server error'}}
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertEqual(result['server_message'], 'Internal server error')


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestExtractServerMessage(unittest.TestCase):
    """Tests for _extract_server_message()."""

    def test_none_response(self):
        self.assertIsNone(_extract_server_message(None))

    def test_json_error_message(self):
        resp = MagicMock()
        resp.json.return_value = {'error': {'message': 'Something went wrong.'}}
        self.assertEqual(_extract_server_message(resp), 'Something went wrong.')

    def test_strips_retry_suffix(self):
        """Strips 'Please try again later.' suffix since the app retries automatically."""
        resp = MagicMock()
        resp.json.return_value = {'error': {'message': 'Rate limited. Please try again later.'}}
        self.assertEqual(_extract_server_message(resp), 'Rate limited.')

    def test_empty_message(self):
        resp = MagicMock()
        resp.json.return_value = {'error': {'message': ''}}
        self.assertIsNone(_extract_server_message(resp))

    def test_no_error_key(self):
        resp = MagicMock()
        resp.json.return_value = {'status': 'ok'}
        self.assertIsNone(_extract_server_message(resp))

    def test_html_body(self):
        resp = MagicMock()
        resp.json.side_effect = ValueError('not JSON')
        self.assertIsNone(_extract_server_message(resp))


class TestParseRetryAfter(unittest.TestCase):
    """Tests for _parse_retry_after()."""

    def test_none_response(self):
        self.assertIsNone(_parse_retry_after(None))

    def test_valid_integer(self):
        resp = MagicMock()
        resp.headers = {'Retry-After': '120'}
        self.assertEqual(_parse_retry_after(resp), 120)

    def test_zero_value(self):
        resp = MagicMock()
        resp.headers = {'Retry-After': '0'}
        self.assertEqual(_parse_retry_after(resp), 0)

    def test_negative_clamped_to_zero(self):
        resp = MagicMock()
        resp.headers = {'Retry-After': '-5'}
        self.assertEqual(_parse_retry_after(resp), 0)

    def test_missing_header(self):
        resp = MagicMock()
        resp.headers = {}
        self.assertIsNone(_parse_retry_after(resp))

    def test_non_numeric_value(self):
        resp = MagicMock()
        resp.headers = {'Retry-After': 'Wed, 21 Oct 2026 07:28:00 GMT'}
        self.assertIsNone(_parse_retry_after(resp))


# ---------------------------------------------------------------------------
# read_access_token (macOS Keychain branch)
# ---------------------------------------------------------------------------

@unittest.skipUnless(_IS_DARWIN, 'macOS-only branch')
class TestReadAccessTokenMacOS(unittest.TestCase):
    """Tests for the Keychain-backed branch of read_access_token() on macOS."""

    def setUp(self):
        import usage_monitor_for_claude.api as api_mod
        api_mod._resolved_keychain_service = None
        api_mod._keychain_discovery_done = False

    def _completed(self, stdout: str, returncode: int = 0):
        result = MagicMock()
        result.stdout = stdout
        result.returncode = returncode
        return result

    def test_returns_token_from_legacy_service(self):
        """Legacy service name 'Claude Code-credentials' returns the access token."""
        creds = {'claudeAiOauth': {'accessToken': 'sk-keychain-legacy'}}
        with patch('usage_monitor_for_claude.api.subprocess.run') as run:
            run.return_value = self._completed(json.dumps(creds))
            with patch('usage_monitor_for_claude.api._find_macos_hashed_keychain_service', return_value=None):
                self.assertEqual(read_access_token(), 'sk-keychain-legacy')

    def test_returns_token_from_hashed_service(self):
        """Hashed service name 'Claude Code-credentials-<HASH>' is discovered and used."""
        creds = {'claudeAiOauth': {'accessToken': 'sk-keychain-hashed'}}
        with patch('usage_monitor_for_claude.api._find_macos_hashed_keychain_service', return_value='Claude Code-credentials-abc123'):
            with patch('usage_monitor_for_claude.api.subprocess.run') as run:
                run.return_value = self._completed(json.dumps(creds))
                self.assertEqual(read_access_token(), 'sk-keychain-hashed')

    def test_security_command_missing_returns_none(self):
        """If /usr/bin/security fails, read_access_token() returns None instead of raising."""
        with patch('usage_monitor_for_claude.api._find_macos_hashed_keychain_service', return_value=None):
            with patch('usage_monitor_for_claude.api.subprocess.run', side_effect=OSError):
                self.assertIsNone(read_access_token())

    def test_security_command_nonzero_exit_returns_none(self):
        """Non-zero exit code from security (e.g. item not found) returns None."""
        with patch('usage_monitor_for_claude.api._find_macos_hashed_keychain_service', return_value=None):
            with patch('usage_monitor_for_claude.api.subprocess.run') as run:
                run.return_value = self._completed('', returncode=44)
                self.assertIsNone(read_access_token())

    def test_security_command_empty_stdout_returns_none(self):
        """Empty stdout returns None."""
        with patch('usage_monitor_for_claude.api._find_macos_hashed_keychain_service', return_value=None):
            with patch('usage_monitor_for_claude.api.subprocess.run') as run:
                run.return_value = self._completed('')
                self.assertIsNone(read_access_token())

    def test_security_command_malformed_json_returns_none(self):
        """Malformed Keychain payload returns None instead of raising."""
        with patch('usage_monitor_for_claude.api._find_macos_hashed_keychain_service', return_value=None):
            with patch('usage_monitor_for_claude.api.subprocess.run') as run:
                run.return_value = self._completed('not json')
                self.assertIsNone(read_access_token())

    def test_security_command_missing_oauth_key_returns_none(self):
        """Keychain payload without claudeAiOauth.accessToken returns None."""
        with patch('usage_monitor_for_claude.api._find_macos_hashed_keychain_service', return_value=None):
            with patch('usage_monitor_for_claude.api.subprocess.run') as run:
                run.return_value = self._completed('{"otherKey": {}}')
                self.assertIsNone(read_access_token())

    def test_security_command_timeout_returns_none(self):
        """A hung security subprocess returns None (timeout caught, not propagated)."""
        import subprocess
        with patch('usage_monitor_for_claude.api._find_macos_hashed_keychain_service', return_value=None):
            with patch('usage_monitor_for_claude.api.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='security', timeout=3)):
                self.assertIsNone(read_access_token())

    def test_token_never_written_to_disk(self):
        """The Mac branch never writes the token (or any other data) to disk."""
        creds = {'claudeAiOauth': {'accessToken': 'sk-no-write'}}
        with patch('usage_monitor_for_claude.api._find_macos_hashed_keychain_service', return_value=None):
            with patch('usage_monitor_for_claude.api.subprocess.run') as run:
                run.return_value = self._completed(json.dumps(creds))
                with patch('builtins.open') as open_mock:
                    read_access_token()
                    open_mock.assert_not_called()

    def test_keychain_discovery_runs_once_for_legacy_install(self):
        """With no hashed entry, the expensive keychain dump runs once, not per read."""
        creds = {'claudeAiOauth': {'accessToken': 'sk-keychain-legacy'}}
        with patch('usage_monitor_for_claude.api.subprocess.run') as run:
            run.return_value = self._completed(json.dumps(creds))
            with patch('usage_monitor_for_claude.api._find_macos_hashed_keychain_service', return_value=None) as discover:
                self.assertEqual(read_access_token(), 'sk-keychain-legacy')
                self.assertEqual(read_access_token(), 'sk-keychain-legacy')
                self.assertEqual(read_access_token(), 'sk-keychain-legacy')
                discover.assert_called_once()

    def test_invalidate_cache_forces_keychain_rediscovery(self):
        """A 401-triggered cache invalidation makes the next read re-run discovery."""
        import usage_monitor_for_claude.api as api_mod
        creds = {'claudeAiOauth': {'accessToken': 'sk-keychain-legacy'}}
        with patch('usage_monitor_for_claude.api.subprocess.run') as run:
            run.return_value = self._completed(json.dumps(creds))
            with patch('usage_monitor_for_claude.api._find_macos_hashed_keychain_service', return_value=None) as discover:
                read_access_token()
                api_mod._invalidate_keychain_cache()
                read_access_token()
                self.assertEqual(discover.call_count, 2)


# ---------------------------------------------------------------------------
# _merge_scoped_limits
# ---------------------------------------------------------------------------

_FIVE_HOUR_RESET = '2026-07-02T10:19:59.752884+00:00'
_SEVEN_DAY_RESET = '2026-07-09T02:59:59.752905+00:00'


def _response_with_scoped(display_name, percent, resets_at):
    """Build a usage response carrying one model-scoped weekly limit."""
    return {
        'five_hour': {'utilization': 4.0, 'resets_at': _FIVE_HOUR_RESET},
        'seven_day': {'utilization': 1.0, 'resets_at': _SEVEN_DAY_RESET},
        'limits': [
            {'kind': 'session', 'group': 'session', 'percent': 4, 'resets_at': _FIVE_HOUR_RESET, 'scope': None},
            {'kind': 'weekly_all', 'group': 'weekly', 'percent': 1, 'resets_at': _SEVEN_DAY_RESET, 'scope': None},
            {'kind': 'weekly_scoped', 'group': 'weekly', 'percent': percent, 'resets_at': resets_at,
             'scope': {'model': {'id': None, 'display_name': display_name}, 'surface': None}},
        ],
    }


class TestMergeScopedLimits(unittest.TestCase):
    """Tests for _merge_scoped_limits()."""

    def test_no_limits_key_passthrough(self):
        """A response without a 'limits' array is returned unchanged."""
        data = {'five_hour': {'utilization': 42.0}}
        self.assertEqual(_merge_scoped_limits(data), {'five_hour': {'utilization': 42.0}})

    def test_limits_not_a_list_passthrough(self):
        """A non-list 'limits' value is ignored."""
        data = {'seven_day': {'utilization': 1.0}, 'limits': None}
        self.assertEqual(_merge_scoped_limits(data), data)

    def test_active_scoped_limit_becomes_field(self):
        """An active model-scoped weekly limit becomes a synthetic quota field."""
        result = _merge_scoped_limits(_response_with_scoped('Fable', 30, _SEVEN_DAY_RESET))
        self.assertEqual(result['seven_day_fable'], {'utilization': 30.0, 'resets_at': _SEVEN_DAY_RESET})

    def test_percent_is_float(self):
        """The integer 'percent' is exposed as a float 'utilization'."""
        result = _merge_scoped_limits(_response_with_scoped('Fable', 30, _SEVEN_DAY_RESET))
        self.assertIsInstance(result['seven_day_fable']['utilization'], float)

    def test_inactive_scoped_limit_still_exposed(self):
        """A scoped limit without a reset window is exposed at 0% with resets_at None."""
        result = _merge_scoped_limits(_response_with_scoped('Fable', 0, None))
        self.assertEqual(result['seven_day_fable'], {'utilization': 0.0, 'resets_at': None})

    def test_existing_top_level_field_not_overwritten(self):
        """A top-level field wins over a scoped limit for the same model."""
        data = _response_with_scoped('Sonnet', 50, _SEVEN_DAY_RESET)
        data['seven_day_sonnet'] = {'utilization': 55.0, 'resets_at': _SEVEN_DAY_RESET}
        result = _merge_scoped_limits(data)
        self.assertEqual(result['seven_day_sonnet']['utilization'], 55.0)

    def test_scoped_without_base_group_skipped(self):
        """Without a non-scoped limit of the same group, no prefix can be derived."""
        data = {
            'five_hour': {'utilization': 4.0, 'resets_at': _FIVE_HOUR_RESET},
            'seven_day': {'utilization': 1.0, 'resets_at': _SEVEN_DAY_RESET},
            'limits': [
                {'kind': 'weekly_scoped', 'group': 'weekly', 'percent': 30, 'resets_at': _SEVEN_DAY_RESET,
                 'scope': {'model': {'display_name': 'Fable'}}},
            ],
        }
        self.assertNotIn('seven_day_fable', _merge_scoped_limits(data))

    def test_input_not_mutated(self):
        """The original response dict is not mutated in place."""
        data = _response_with_scoped('Fable', 30, _SEVEN_DAY_RESET)
        _merge_scoped_limits(data)
        self.assertNotIn('seven_day_fable', data)

    def test_original_fields_preserved(self):
        """Existing top-level quota fields survive the merge unchanged."""
        result = _merge_scoped_limits(_response_with_scoped('Fable', 30, _SEVEN_DAY_RESET))
        self.assertEqual(result['five_hour']['utilization'], 4.0)
        self.assertEqual(result['seven_day']['utilization'], 1.0)


# ---------------------------------------------------------------------------
# _model_slug
# ---------------------------------------------------------------------------

class TestModelSlug(unittest.TestCase):
    """Tests for _model_slug()."""

    def test_single_word(self):
        self.assertEqual(_model_slug('Fable'), 'fable')

    def test_multi_word(self):
        self.assertEqual(_model_slug('Claude Sonnet'), 'claude_sonnet')

    def test_digits_and_punctuation(self):
        self.assertEqual(_model_slug('Opus 4.5'), 'opus_4_5')


if __name__ == '__main__':
    unittest.main()
