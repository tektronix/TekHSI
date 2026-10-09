"""Wiring tests for TekHSIConnect security integration."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
from unittest.mock import MagicMock, patch

import grpc
import pytest

from tekhsi.credential_store import CertInfo
from tekhsi.security import TekAuthenticationFailed, TekCertificateMismatch
from tekhsi.tek_hsi_connect import TekHSIConnect

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


TEST_PASSWORD = "test-" + "credential"


def _private_method(instance: Any, name: str) -> Any:
    """Return a named private method for focused wiring tests."""
    return getattr(instance, name)


@pytest.fixture(name="mock_insecure_channel")
def fixture_mock_insecure_channel() -> MagicMock:
    """Patch grpc.insecure_channel for legacy-path tests."""
    channel = MagicMock()
    with patch("tekhsi.tek_hsi_connect.grpc.insecure_channel", return_value=channel) as mock:
        yield mock


def test_legacy_plain_uses_insecure_channel(mock_insecure_channel: MagicMock) -> None:
    """Legacy TekHSIConnect(url) uses insecure channel with no store or probe."""
    with (
        patch.object(TekHSIConnect, "_connect"),
        patch.object(TekHSIConnect, "_available_symbols", return_value=[]),
        patch("tekhsi.tek_hsi_connect.TekCredentialStore") as mock_store_cls,
        patch("tekhsi.security._try_plain_grpc_channel") as mock_probe,
    ):
        client = TekHSIConnect("127.0.0.1:5000")

    mock_insecure_channel.assert_called_once_with("127.0.0.1:5000")
    mock_store_cls.assert_not_called()
    mock_probe.assert_not_called()
    assert vars(client)["_auto_security"] is False
    assert vars(client)["_credential_store_ref"] is None
    assert vars(client)["_on_trust_ref"] is None


def test_timeout_alone_does_not_enable_security(mock_insecure_channel: MagicMock) -> None:
    """Passing timeout= alone keeps legacy plain path."""
    with (
        patch.object(TekHSIConnect, "_connect"),
        patch.object(TekHSIConnect, "_available_symbols", return_value=[]),
        patch("tekhsi.tek_hsi_connect.TekCredentialStore") as mock_store_cls,
    ):
        client = TekHSIConnect("127.0.0.1:5000", timeout=30.0)

    mock_insecure_channel.assert_called_once()
    mock_store_cls.assert_not_called()
    assert vars(client)["_auto_security"] is False


def test_require_tls_opens_security_path() -> None:
    """require_tls=True enters auto-negotiation even without explicit store."""
    mock_channel = MagicMock()
    with (
        patch("tekhsi.tek_hsi_connect._auto_negotiate_channel", return_value=mock_channel),
        patch.object(TekHSIConnect, "_connect"),
        patch.object(TekHSIConnect, "_available_symbols", return_value=[]),
        patch("tekhsi.tek_hsi_connect.TekCredentialStore") as mock_store_cls,
    ):
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store
        client = TekHSIConnect("127.0.0.1:5000", require_tls=True)

    assert vars(client)["_auto_security"] is True
    mock_store_cls.assert_called_once()


def test_legacy_unauthenticated_raises_raw_grpc_error() -> None:
    """Legacy caller gets raw RpcError on UNAUTHENTICATED, not TekAuthenticationFailed."""
    client = TekHSIConnect.__new__(TekHSIConnect)
    client.url = "127.0.0.1:5000"
    client.clientname = "test-client"
    vars(client)["_auto_security"] = False
    client.connection = MagicMock()

    class FakeRpcError(grpc.RpcError):
        """Minimal fake RpcError reporting UNAUTHENTICATED."""

        def code(self) -> grpc.StatusCode:
            """Return UNAUTHENTICATED status code."""
            return grpc.StatusCode.UNAUTHENTICATED

        def details(self) -> str:
            """Return a fixed detail message."""
            return "auth required"

    client.connection.Connect.side_effect = FakeRpcError()

    with pytest.raises(FakeRpcError):
        _private_method(client, "_connect")()


class FakeUnauthenticatedError(grpc.RpcError):
    """A fake gRPC UNAUTHENTICATED error usable as a Connect() side effect."""

    def __init__(self, detail: str = "auth required") -> None:
        """Create an error carrying the server detail text."""
        self._detail = detail

    def code(self) -> grpc.StatusCode:
        """Return UNAUTHENTICATED status code."""
        return grpc.StatusCode.UNAUTHENTICATED

    def details(self) -> str:
        """Return the configured detail message."""
        return self._detail


def _make_auto_security_client() -> TekHSIConnect:
    """Build a bare TekHSIConnect instance with auto_security enabled."""
    client = TekHSIConnect.__new__(TekHSIConnect)
    client.url = "127.0.0.1:5000"
    client.clientname = "test-client"
    vars(client)["_auto_security"] = True
    vars(client)["_verbose"] = False
    client.connection = MagicMock()
    return client


def test_connect_upgrades_once_then_succeeds() -> None:
    """First UNAUTHENTICATED triggers exactly one upgrade, then Connect succeeds."""
    client = _make_auto_security_client()
    success_reply = MagicMock(protocol_version=0, capabilities=0)
    client.connection.Connect.side_effect = [FakeUnauthenticatedError(), success_reply]

    with patch.object(
        TekHSIConnect, "_upgrade_channel_with_token_after_unauthenticated"
    ) as mock_upgrade:
        _private_method(client, "_connect")()

    mock_upgrade.assert_called_once()
    assert client.connection.Connect.call_count == 2


def test_connect_upgrade_failure_wraps_second_unauthenticated() -> None:
    """A second UNAUTHENTICATED after the upgrade raises TekAuthenticationFailed with context."""
    client = _make_auto_security_client()
    client.connection.Connect.side_effect = [
        FakeUnauthenticatedError("first"),
        FakeUnauthenticatedError("still bad"),
    ]

    with (
        patch.object(TekHSIConnect, "_upgrade_channel_with_token_after_unauthenticated"),
        pytest.raises(TekAuthenticationFailed),
    ):
        _private_method(client, "_connect")()


def test_connect_auto_security_unauthenticated_without_upgrade_path() -> None:
    """auto_security=True but no upgrade available still raises TekAuthenticationFailed."""
    client = _make_auto_security_client()
    client.connection.Connect.side_effect = FakeUnauthenticatedError("no creds")
    # Force the upgrade attempt itself to raise (e.g. no store/callback), simulating
    # a server that demands auth but the caller gave TekHSIConnect no way to respond.
    with (
        patch.object(
            TekHSIConnect,
            "_upgrade_channel_with_token_after_unauthenticated",
            side_effect=TekAuthenticationFailed(client.url, "no store"),
        ),
        pytest.raises(TekAuthenticationFailed),
    ):
        _private_method(client, "_connect")()


def _make_upgrade_client(
    store: MagicMock, on_trust_prompt: Callable[..., Any] | None
) -> TekHSIConnect:
    client = TekHSIConnect.__new__(TekHSIConnect)
    client.url = "127.0.0.1:5000"
    vars(client)["_credential_store_ref"] = store
    vars(client)["_on_trust_ref"] = on_trust_prompt
    client.channel = MagicMock()
    return client


class TestUpgradeChannelWithTokenAfterUnauthenticated:
    """Direct tests for the Mode-3 upgrade helper."""

    def test_missing_store_or_callback_raises(self) -> None:
        """Reject upgrades without credential storage or a trust callback."""
        client = _make_upgrade_client(store=None, on_trust_prompt=None)
        with pytest.raises(TekAuthenticationFailed):
            _private_method(client, "_upgrade_channel_with_token_after_unauthenticated")()

    def test_missing_cert_path_in_store_raises(self) -> None:
        """Reject upgrades when the stored certificate path is missing."""
        store = MagicMock()
        store.get.return_value = {"cert_path": None}
        client = _make_upgrade_client(store=store, on_trust_prompt=lambda: True)
        with pytest.raises(TekAuthenticationFailed):
            _private_method(client, "_upgrade_channel_with_token_after_unauthenticated")()

    def test_certificate_mismatch_raises(self, tmp_path: Path) -> None:
        """Reject a server certificate that differs from the stored certificate."""
        store = MagicMock()
        store.get.return_value = {"cert_path": str(tmp_path / "x.pem"), "cert_fingerprint": "aaa"}
        client = _make_upgrade_client(store=store, on_trust_prompt=lambda: True)
        with (
            patch("tekhsi.tek_hsi_connect._parse_host_port", return_value=("127.0.0.1", 5000)),
            patch(
                "tekhsi.tek_hsi_connect._fetch_server_cert",
                return_value=CertInfo(cert_fingerprint="bbb"),
            ),
            pytest.raises(TekCertificateMismatch),
        ):
            _private_method(client, "_upgrade_channel_with_token_after_unauthenticated")()

    def test_declined_prompt_raises_authentication_failed(self, tmp_path: Path) -> None:
        """Reject upgrades when the trust prompt declines the certificate."""
        store = MagicMock()
        store.get.return_value = {"cert_path": str(tmp_path / "x.pem"), "cert_fingerprint": "aaa"}
        client = _make_upgrade_client(store=store, on_trust_prompt=lambda: False)
        with (
            patch("tekhsi.tek_hsi_connect._parse_host_port", return_value=("127.0.0.1", 5000)),
            patch(
                "tekhsi.tek_hsi_connect._fetch_server_cert",
                return_value=CertInfo(cert_fingerprint="aaa"),
            ),
            patch("tekhsi.tek_hsi_connect._call_on_trust", return_value=False),
            pytest.raises(TekAuthenticationFailed),
        ):
            _private_method(client, "_upgrade_channel_with_token_after_unauthenticated")()

    def test_true_without_password_raises(self, tmp_path: Path) -> None:
        """Reject a trust decision that does not provide the required password."""
        store = MagicMock()
        store.get.return_value = {"cert_path": str(tmp_path / "x.pem"), "cert_fingerprint": "aaa"}
        client = _make_upgrade_client(store=store, on_trust_prompt=lambda: True)
        with (
            patch("tekhsi.tek_hsi_connect._parse_host_port", return_value=("127.0.0.1", 5000)),
            patch(
                "tekhsi.tek_hsi_connect._fetch_server_cert",
                return_value=CertInfo(cert_fingerprint="aaa"),
            ),
            patch("tekhsi.tek_hsi_connect._call_on_trust", return_value=True),
            pytest.raises(TekAuthenticationFailed),
        ):
            _private_method(client, "_upgrade_channel_with_token_after_unauthenticated")()

    def test_successful_upgrade_rebinds_channel_and_stubs(self, tmp_path: Path) -> None:
        """A full successful upgrade persists creds and rebinds channel/stubs."""
        store = MagicMock()
        cert_path = str(tmp_path / "x.pem")
        entry_before = {"cert_path": cert_path, "cert_fingerprint": "aaa"}
        entry_after = {"cert_path": cert_path, "cert_fingerprint": "aaa", "password": "obf1:xx"}
        store.get.side_effect = [entry_before, entry_after]
        client = _make_upgrade_client(
            store=store, on_trust_prompt=lambda: (True, TEST_PASSWORD, "user1")
        )
        new_channel = MagicMock()

        with (
            patch("tekhsi.tek_hsi_connect._parse_host_port", return_value=("127.0.0.1", 5000)),
            patch(
                "tekhsi.tek_hsi_connect._fetch_server_cert",
                return_value=CertInfo(cert_fingerprint="aaa"),
            ),
            patch(
                "tekhsi.tek_hsi_connect._call_on_trust",
                return_value=(True, TEST_PASSWORD, "user1"),
            ),
            patch("tekhsi.tek_hsi_connect._build_creds_from_entry", return_value=MagicMock()),
            patch("tekhsi.tek_hsi_connect._secure_channel", return_value=new_channel),
        ):
            _private_method(client, "_upgrade_channel_with_token_after_unauthenticated")()

        store.set.assert_called_once_with(client.url, password=TEST_PASSWORD, login="user1")
        store.save.assert_called_once()
        assert client.channel is new_channel
        assert client.connection is not None
        assert client.native is not None
