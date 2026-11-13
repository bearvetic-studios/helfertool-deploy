"""Relay internal SMTP to Graph using a delegated, persisted user session."""

import argparse
import asyncio
import base64
import logging
import os
import re
import signal
import smtplib
import threading
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from email.utils import formataddr, getaddresses, parseaddr
from pathlib import Path
from uuid import UUID

import msal
import requests
from aiosmtpd.controller import Controller
from msal_extensions import FilePersistence, PersistedTokenCache


LOG = logging.getLogger("graph-relay")
SCOPES = ["https://graph.microsoft.com/Mail.Send.Shared"]
GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"
MAX_SMTP_BYTES = 3_000_000
MAX_GRAPH_BYTES = 4_000_000
SMTP_PORT = 8025


class RelayError(Exception):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


def valid_address(value: str) -> bool:
    return (
        bool(value) and "@" in value and "\r" not in value and "\n" not in value
        and parseaddr(value)[1] == value
    )


@dataclass(frozen=True)
class Settings:
    tenant_id: str
    client_id: str
    username: str
    sender_address: str
    sender_name: str
    cache_path: Path = Path("/data/msal-cache.json")

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "Settings":
        required = (
            "OAUTH_TENANT_ID", "OAUTH_CLIENT_ID", "OAUTH_USERNAME", "SMTP_SENDER_ADDRESS",
        )
        values = {key: env.get(key, "").strip() for key in required}
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise ValueError("Missing required settings: " + ", ".join(missing))
        for key in ("OAUTH_TENANT_ID", "OAUTH_CLIENT_ID"):
            try:
                UUID(values[key])
            except ValueError as error:
                raise ValueError(f"{key} must be a GUID.") from error
        for key in ("OAUTH_USERNAME", "SMTP_SENDER_ADDRESS"):
            if not valid_address(values[key]):
                raise ValueError(f"{key} must be a single email address.")
        name = env.get("SMTP_SENDER_NAME", "").strip()
        if "\r" in name or "\n" in name:
            raise ValueError("SMTP_SENDER_NAME must not contain line breaks.")
        return cls(
            values["OAUTH_TENANT_ID"], values["OAUTH_CLIENT_ID"],
            values["OAUTH_USERNAME"], values["SMTP_SENDER_ADDRESS"], name,
        )


def prepare_mime(raw: bytes, recipients: list[str], settings: Settings) -> bytes:
    """Keep MIME content, but use SMTP envelope recipients without leaking Bcc."""
    if len(raw) > MAX_SMTP_BYTES:
        raise RelayError("552 5.3.4 Message exceeds the 3 MB relay limit")
    if not recipients or any(not valid_address(address) for address in recipients):
        raise RelayError("550 5.1.3 Invalid envelope recipients")
    message = BytesParser(policy=policy.SMTP).parsebytes(raw)
    senders = getaddresses(message.get_all("From", []))
    if len(senders) != 1 or senders[0][1].casefold() != settings.sender_address.casefold():
        raise RelayError("553 5.7.1 From address is not permitted")

    remaining = {address.casefold(): address for address in recipients}
    for header in ("To", "Cc"):
        addresses = getaddresses(message.get_all(header, []))
        del message[header]
        visible = []
        for name, address in addresses:
            if address.casefold() in remaining:
                visible.append(formataddr((name, remaining.pop(address.casefold()))))
        if visible:
            message[header] = ", ".join(visible)
    del message["Bcc"]
    if remaining:
        message["Bcc"] = ", ".join(remaining.values())
    # Graph must not inherit stale delegation or re-send headers from the client.
    for header in list(message.keys()):
        if header.lower() in {"from", "sender", "return-path"} or header.lower().startswith("resent-"):
            del message[header]
    message["From"] = formataddr((settings.sender_name, settings.sender_address))
    encoded = base64.b64encode(message.as_bytes())
    if len(encoded) > MAX_GRAPH_BYTES:
        raise RelayError("552 5.3.4 Encoded message exceeds the Graph request limit")
    return encoded


class GraphClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._application: msal.PublicClientApplication | None = None
        self._lock = threading.Lock()

    def application(self) -> msal.PublicClientApplication:
        if self._application is None:
            directory = self.settings.cache_path.parent
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
            cache = PersistedTokenCache(FilePersistence(str(self.settings.cache_path)))
            self._application = msal.PublicClientApplication(
                self.settings.client_id,
                authority=f"https://login.microsoftonline.com/{self.settings.tenant_id}",
                token_cache=cache,
                timeout=30,
            )
        return self._application

    def token(self, force_refresh: bool = False) -> str:
        with self._lock:
            app = self.application()
            accounts = app.get_accounts(username=self.settings.username)
            if not accounts:
                raise RelayError("451 4.7.0 Graph login required; run the relay login command")
            result = app.acquire_token_silent(SCOPES, account=accounts[0], force_refresh=force_refresh)
            if not result or "access_token" not in result:
                raise RelayError("451 4.7.0 Graph session expired or revoked; repeat relay login")
            return result["access_token"]

    def login(self) -> None:
        app = self.application()
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RelayError("Device login could not start; check app registration and tenant policy")
        print(flow["message"], flush=True)
        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RelayError("Device login failed; check consent, MFA and tenant sign-in logs")
        username = result.get("id_token_claims", {}).get("preferred_username", "")
        if username.casefold() != self.settings.username.casefold():
            raise RelayError("Signed-in account does not match OAUTH_USERNAME; repeat login")
        print("Graph login saved for the configured user.", flush=True)

    def send(self, raw: bytes, recipients: list[str]) -> None:
        try:
            encoded = prepare_mime(raw, recipients, self.settings)
        except ValueError as error:
            raise RelayError("550 5.6.0 Invalid message headers") from error
        try:
            for force_refresh in (False, True):
                response = requests.post(
                    GRAPH_SEND_URL,
                    headers={
                        "Authorization": f"Bearer {self.token(force_refresh=force_refresh)}",
                        "Content-Type": "text/plain",
                    },
                    data=encoded, timeout=30, allow_redirects=False,
                )
                if response.status_code != 401:
                    break
        except requests.RequestException as error:
            raise RelayError("451 4.4.2 Graph connection failed; delivery outcome may be unknown") from error
        except ValueError as error:
            raise RelayError("451 4.7.0 OAuth initialization failed; check app registration") from error
        if response.status_code != 202:
            try:
                code = response.json().get("error", {}).get("code", "")
            except (ValueError, AttributeError):
                code = ""
            code = re.sub(r"[^a-zA-Z0-9_.-]", "", str(code))[:80]
            detail = f"Graph HTTP {response.status_code} {code}".strip()
            if response.status_code == 413:
                raise RelayError(f"552 5.3.4 {detail}")
            if 400 <= response.status_code < 500 and response.status_code not in {401, 408, 429}:
                raise RelayError(f"550 5.7.1 {detail}")
            raise RelayError(f"451 4.7.0 {detail}; retry later or repeat relay login")
        LOG.info("Graph accepted the message (202); final delivery remains subject to Exchange")


class SmtpHandler:
    def __init__(self, client: GraphClient):
        self.client = client

    async def handle_MAIL(self, server, session, envelope, address, mail_options):
        if address.casefold() != self.client.settings.sender_address.casefold():
            return "553 5.7.1 Envelope sender is not permitted"
        envelope.mail_from = address
        envelope.mail_options.extend(mail_options)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        try:
            await asyncio.to_thread(
                self.client.send, envelope.original_content, envelope.rcpt_tos,
            )
        except RelayError as error:
            LOG.error("%s", error.status)
            return error.status
        return "250 2.0.0 Accepted by Microsoft Graph"


def serve(client: GraphClient) -> None:
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    controller = Controller(
        SmtpHandler(client), hostname="0.0.0.0", port=SMTP_PORT,
        data_size_limit=MAX_SMTP_BYTES, enable_SMTPUTF8=True,
    )
    controller.start()
    LOG.info("Internal SMTP listening on port %d; delegated Graph login required before sending", SMTP_PORT)
    try:
        stop.wait()
    finally:
        controller.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve", "login", "healthcheck"), nargs="?", default="serve")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if arguments.command == "healthcheck":
            with smtplib.SMTP("127.0.0.1", SMTP_PORT, timeout=5) as connection:
                code, response = connection.noop()
                if code != 250:
                    raise smtplib.SMTPResponseException(code, response)
        else:
            client = GraphClient(Settings.from_env(dict(os.environ)))
            if arguments.command == "login":
                client.login()
            else:
                serve(client)
    except (ValueError, OSError, RelayError, requests.RequestException) as error:
        if isinstance(error, (RelayError, ValueError)):
            LOG.error("%s", error)
        else:
            LOG.error("Relay network or storage operation failed (%s)", type(error).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
