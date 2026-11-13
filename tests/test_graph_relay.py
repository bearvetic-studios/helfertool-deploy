import asyncio
import base64
import smtplib
import sys
import unittest
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import Mock, call, patch

from aiosmtpd.smtp import SMTP

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "relay"))

import graph_relay  # noqa: E402


def settings():
    return graph_relay.Settings(
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "login@example.org", "helfer@example.org", "Helfer Team",
    )


def message_bytes():
    message = EmailMessage(policy=policy.SMTP)
    message["From"] = "Helfer <helfer@example.org>"
    message["To"] = "Visible <visible@example.org>, not-in-envelope@example.org"
    message["Cc"] = "copy@example.org"
    message["Bcc"] = "other-not-in-envelope@example.org"
    message["Subject"] = "Graph relay test"
    message.set_content("Test body")
    message.add_attachment(b"attachment-content", maintype="application", subtype="pdf", filename="test.pdf")
    return message.as_bytes()


class GraphRelayTests(unittest.TestCase):
    def test_mime_keeps_attachments_and_uses_only_envelope_recipients_without_bcc_leak(self):
        raw = message_bytes()
        encoded = graph_relay.prepare_mime(
            raw, ["visible@example.org", "copy@example.org", "hidden@example.org"], settings(),
        )
        message = BytesParser(policy=policy.SMTP).parsebytes(base64.b64decode(encoded))
        self.assertEqual(str(message["From"]), "Helfer Team <helfer@example.org>")
        self.assertEqual(str(message["To"]), "Visible <visible@example.org>")
        self.assertEqual(str(message["Cc"]), "copy@example.org")
        self.assertEqual(str(message["Bcc"]), "hidden@example.org")
        self.assertNotIn("hidden@example.org", str(message["To"]) + str(message["Cc"]))
        self.assertEqual(message.get_body(preferencelist=("plain",)).get_content().strip(), "Test body")
        self.assertEqual(next(message.iter_attachments()).get_payload(decode=True), b"attachment-content")

    def test_rejects_spoofed_or_duplicate_from_headers(self):
        for raw in (
            message_bytes().replace(b"helfer@example.org", b"spoof@example.org"),
            b"From: helfer@example.org\r\n" + message_bytes(),
        ):
            with self.subTest(raw=raw[:80]):
                with self.assertRaisesRegex(graph_relay.RelayError, "^553"):
                    graph_relay.prepare_mime(raw, ["recipient@example.org"], settings())

    def test_rejects_oversize_mime_and_enforces_exact_encoded_limit(self):
        with self.assertRaisesRegex(graph_relay.RelayError, "^552"):
            graph_relay.prepare_mime(
                b"x" * (3_000_000 + 1), ["recipient@example.org"], settings(),
            )
        raw = message_bytes()
        encoded = graph_relay.prepare_mime(raw, ["recipient@example.org"], settings())
        with patch.object(graph_relay, "MAX_GRAPH_BYTES", len(encoded)):
            self.assertEqual(
                graph_relay.prepare_mime(raw, ["recipient@example.org"], settings()), encoded,
            )
        with patch.object(graph_relay, "MAX_GRAPH_BYTES", len(encoded) - 1):
            with self.assertRaisesRegex(graph_relay.RelayError, "^552"):
                graph_relay.prepare_mime(raw, ["recipient@example.org"], settings())

    def test_uses_only_configured_cached_user_and_silent_token_acquisition(self):
        app = Mock()
        account = {"username": "login@example.org"}
        app.get_accounts.return_value = [account]
        app.acquire_token_silent.return_value = {"access_token": "test-token"}
        client = graph_relay.GraphClient(settings())
        with patch.object(client, "application", return_value=app):
            self.assertEqual(client.token(), "test-token")
        app.get_accounts.assert_called_once_with(username="login@example.org")
        app.acquire_token_silent.assert_called_once_with(
            graph_relay.SCOPES, account=account, force_refresh=False,
        )
        app.acquire_token_by_device_flow.assert_not_called()

    def test_missing_or_revoked_session_is_an_explicit_temporary_smtp_error(self):
        for accounts, result in (([], None), ([{"username": "login@example.org"}], None)):
            with self.subTest(accounts=accounts):
                client = graph_relay.GraphClient(settings())
                app = Mock()
                app.get_accounts.return_value = accounts
                app.acquire_token_silent.return_value = result
                with patch.object(client, "application", return_value=app):
                    with self.assertRaisesRegex(graph_relay.RelayError, "^451"):
                        client.token()

    def test_device_login_rejects_a_different_user(self):
        app = Mock()
        app.initiate_device_flow.return_value = {"user_code": "code", "message": "Test device login"}
        app.acquire_token_by_device_flow.return_value = {
            "access_token": "test-token",
            "id_token_claims": {"preferred_username": "different@example.org"},
        }
        client = graph_relay.GraphClient(settings())
        with patch.object(client, "application", return_value=app), patch("builtins.print"):
            with self.assertRaisesRegex(graph_relay.RelayError, "does not match OAUTH_USERNAME"):
                client.login()

    def test_send_uses_graph_me_endpoint_and_accepts_only_202(self):
        for status, expected in ((202, None), (403, "550"), (429, "451"), (503, "451"), (413, "552"), (200, "451")):
            with self.subTest(status=status):
                response = Mock(status_code=status)
                response.json.return_value = {"error": {"code": "ErrorSendAsDenied", "message": "private-detail"}}
                client = graph_relay.GraphClient(settings())
                with (
                    patch.object(client, "token", return_value="test-token"),
                    patch.object(graph_relay.requests, "post", return_value=response) as post,
                ):
                    if expected:
                        with self.assertRaisesRegex(graph_relay.RelayError, "^" + expected) as caught:
                            client.send(message_bytes(), ["recipient@example.org"])
                        self.assertNotIn("private-detail", str(caught.exception))
                    else:
                        client.send(message_bytes(), ["recipient@example.org"])
                self.assertEqual(post.call_args.args, ("https://graph.microsoft.com/v1.0/me/sendMail",))
                self.assertEqual(post.call_args.kwargs["headers"]["Content-Type"], "text/plain")
                sent = BytesParser(policy=policy.SMTP).parsebytes(base64.b64decode(post.call_args.kwargs["data"]))
                self.assertEqual(sent["From"].addresses[0].addr_spec, "helfer@example.org")
                self.assertEqual(sent["Bcc"].addresses[0].addr_spec, "recipient@example.org")

    def test_network_failure_does_not_report_success_or_expose_token(self):
        client = graph_relay.GraphClient(settings())
        with (
            patch.object(client, "token", return_value="private-token"),
            patch.object(graph_relay.requests, "post", side_effect=graph_relay.requests.Timeout("private-token")),
        ):
            with self.assertRaisesRegex(graph_relay.RelayError, "^451") as caught:
                client.send(message_bytes(), ["recipient@example.org"])
            self.assertNotIn("private-token", str(caught.exception))

    def test_graph_401_refreshes_silently_once_before_retrying(self):
        client = graph_relay.GraphClient(settings())
        with (
            patch.object(client, "token", return_value="test-token") as token,
            patch.object(
                graph_relay.requests, "post",
                side_effect=[Mock(status_code=401), Mock(status_code=202)],
            ) as post,
        ):
            client.send(message_bytes(), ["recipient@example.org"])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(token.call_args_list, [call(force_refresh=False), call(force_refresh=True)])


class GraphSmtpIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = Mock(settings=settings())
        loop = asyncio.get_running_loop()
        self.server = await loop.create_server(
            lambda: SMTP(graph_relay.SmtpHandler(self.client), data_size_limit=3_000_000),
            "127.0.0.1", 0,
        )
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    def send(self, sender="helfer@example.org"):
        with smtplib.SMTP("127.0.0.1", self.port, timeout=5) as connection:
            return connection.sendmail(sender, ["recipient@example.org"], message_bytes())

    async def test_smtp_success_only_after_graph_acceptance(self):
        self.assertEqual(await asyncio.to_thread(self.send), {})
        self.client.send.assert_called_once()

    async def test_graph_or_login_errors_reach_smtp_client(self):
        for status in ("451 4.7.0 Graph login required", "550 5.7.1 ErrorSendAsDenied"):
            with self.subTest(status=status):
                self.client.send.side_effect = graph_relay.RelayError(status)
                with self.assertRaises(smtplib.SMTPDataError) as caught:
                    await asyncio.to_thread(self.send)
                self.assertEqual(caught.exception.smtp_code, int(status[:3]))

    async def test_smtp_rejects_unapproved_envelope_sender_before_graph_call(self):
        with self.assertRaises(smtplib.SMTPSenderRefused) as caught:
            await asyncio.to_thread(self.send, "spoof@example.org")
        self.assertEqual(caught.exception.smtp_code, 553)
        self.client.send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
