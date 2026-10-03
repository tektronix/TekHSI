"""Wiring tests for TekHSIConnect security integration."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import grpc
import pytest  # pyright: ignore[reportMissingImports]

from typing_extensions import override

from tekhsi.tek_hsi_connect import TekHSIConnect


@pytest.fixture(name="mock_insecure_channel")  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def fixture_mock_insecure_channel() -> Generator[MagicMock, Any, None]:
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
    assert client._auto_security is False  # pyright: ignore[reportPrivateUsage]
    assert client._credential_store_ref is None  # pyright: ignore[reportPrivateUsage]
    assert client._on_trust_ref is None  # pyright: ignore[reportPrivateUsage]


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
    assert client._auto_security is False  # pyright: ignore[reportPrivateUsage]


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

    assert client._auto_security is True  # pyright: ignore[reportPrivateUsage]
    mock_store_cls.assert_called_once()


def test_legacy_unauthenticated_raises_raw_grpc_error() -> None:
    """Legacy caller gets raw RpcError on UNAUTHENTICATED, not TekAuthenticationFailed."""
    client = TekHSIConnect.__new__(TekHSIConnect)
    client.url = "127.0.0.1:5000"
    client.clientname = "test-client"
    client._auto_security = False  # pyright: ignore[reportPrivateUsage]
    client.connection = MagicMock()

    class FakeRpcError(grpc.RpcError):
        @override
        def code(self) -> grpc.StatusCode:
            return grpc.StatusCode.UNAUTHENTICATED

        @override
        def details(self) -> str:
            return "auth required"

    client.connection.Connect.side_effect = FakeRpcError()

    with pytest.raises(FakeRpcError):  # pyright: ignore[reportUnknownMemberType]
        client._connect()  # pyright: ignore[reportPrivateUsage]
