"""
API Client Tests
=================

Unit tests for read_access_token() and fetch_usage().
"""
from __future__ import annotations

import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import MagicMock, patch

from usage_monitor_for_claude.api import API_URL_USAGE, fetch_usage, read_access_token
from usage_monitor_for_claude.i18n import LOCALE_DIR

EN = json.loads((LOCALE_DIR / 'en.json').read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# read_access_token
# ---------------------------------------------------------------------------

class TestReadAccessToken(unittest.TestCase):
    """Tests for read_access_token()."""

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
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertEqual(result['error'], EN['auth_expired'])
        self.assertTrue(result['auth_error'])

    @patch('usage_monitor_for_claude.api.requests.get')
    @patch('usage_monitor_for_claude.api.api_headers', return_value={'Authorization': 'Bearer test'})
    def test_other_http_error(self, _mock_headers, mock_get):
        """Non-401 HTTP error returns http_error with status code."""
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        result = fetch_usage()

        self.assertEqual(result, {'error': EN['http_error'].format(code=500)})

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


if __name__ == '__main__':
    unittest.main()
