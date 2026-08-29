import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import codex_proxy


class CodexProxyTests(unittest.TestCase):
    def test_status_exposes_no_token_material(self):
        with patch("codex_proxy._stored_tokens", return_value=object()):
            status = codex_proxy.fetch_status()
        self.assertEqual(
            status,
            {"ok": True, "authenticated": True, "model": codex_proxy.DEFAULT_MODEL},
        )

    def test_send_chat_refuses_to_open_login_implicitly(self):
        with patch("codex_proxy._stored_tokens", return_value=None):
            with patch("codex_proxy.CodexClient") as client:
                result = codex_proxy.send_chat("rank these")
        self.assertFalse(result["ok"])
        self.assertIn("login required", result["error"])
        client.assert_not_called()

    def test_send_chat_uses_explicit_client_and_closes_it(self):
        client = MagicMock()
        client.responses.create.return_value = [
            SimpleNamespace(type="response.created", delta=""),
            SimpleNamespace(type="response.output_text.delta", delta='{"ranked_ids":'),
            SimpleNamespace(type="response.output_text.delta", delta="[1]}"),
        ]
        tokens = SimpleNamespace(access_token="private-token")
        with patch("codex_proxy._stored_tokens", return_value=tokens):
            with patch("codex_proxy.CodexClient", return_value=client):
                result = codex_proxy.send_chat("rank these")
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], '{"ranked_ids":[1]}')
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertTrue(client.responses.create.call_args.kwargs["stream"])
        client.close.assert_called_once()

    def test_expired_cached_token_is_refreshed_without_interactive_login(self):
        expired = SimpleNamespace(
            access_token="old",
            refresh_token="refresh",
            account_id="account",
            is_expired=lambda: True,
        )
        store = MagicMock()
        store.load.return_value = expired
        refreshed = SimpleNamespace(access_token="new")
        with patch("codex_proxy.TokenStore", return_value=store):
            with patch("codex_proxy.refresh_access_token", return_value={"access_token": "new"}):
                with patch("codex_proxy.AuthTokens.from_response", return_value=refreshed):
                    tokens = codex_proxy._stored_tokens()
        self.assertIs(tokens, refreshed)
        store.save.assert_called_once_with(refreshed)

    def test_login_returns_state_without_exposing_token(self):
        with patch(
            "codex_proxy.authenticate",
            return_value=SimpleNamespace(access_token="private-token"),
        ):
            result = codex_proxy.login()
        self.assertEqual(result, {"ok": True, "authenticated": True})
        self.assertNotIn("token", result)


if __name__ == "__main__":
    unittest.main()
