from __future__ import annotations

import os
from ipaddress import IPv4Address
from types import SimpleNamespace

import pytest

from app.system import network


def test_windows_physical_adapter_query_selects_only_eligible_media(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(arguments: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((arguments, kwargs))
        return SimpleNamespace(returncode=0, stdout="7\tEthernet\n15\tWi-Fi\n")

    monkeypatch.setattr(network.subprocess, "run", fake_run)

    interfaces = network._windows_physical_lan_interfaces()

    assert interfaces == (
        network.PhysicalLanInterface(index=7, name="ethernet"),
        network.PhysicalLanInterface(index=15, name="wi-fi"),
    )
    assert calls == [
        (
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                network._PHYSICAL_ADAPTER_COMMAND,
            ],
            {
                "check": False,
                "capture_output": True,
                "encoding": "utf-8",
                "errors": "replace",
                "timeout": 10,
            },
        )
    ]
    assert "Get-NetAdapter -Physical" in network._PHYSICAL_ADAPTER_COMMAND
    assert "NdisPhysicalMedium -in 14, 9" in network._PHYSICAL_ADAPTER_COMMAND
    assert "Status -eq 'Up'" not in network._PHYSICAL_ADAPTER_COMMAND
    assert "OutputEncoding = [System.Text.Encoding]::UTF8" in network._PHYSICAL_ADAPTER_COMMAND


def test_lan_eligibility_live_filters_cached_physical_adapters(monkeypatch) -> None:
    monkeypatch.setattr(
        network,
        "physical_lan_interfaces",
        lambda: (
            network.PhysicalLanInterface(index=7, name="ethernet"),
            network.PhysicalLanInterface(index=15, name="wi-fi"),
        ),
    )
    monkeypatch.setattr(
        network.psutil,
        "net_if_stats",
        lambda: {
            "Ethernet": SimpleNamespace(isup=False),
            "Wi-Fi": SimpleNamespace(isup=True),
        },
    )

    assert network.eligible_lan_interface_names() == frozenset({"wi-fi"})


@pytest.mark.skipif(os.name != "nt", reason="Windows routing lookup is only used on Windows.")
def test_lan_peer_requires_windows_to_route_over_an_eligible_interface(monkeypatch) -> None:
    peer = IPv4Address("172.20.0.42")
    monkeypatch.setattr(
        network,
        "eligible_lan_interfaces",
        lambda: (network.PhysicalLanInterface(index=7, name="ethernet"),),
    )
    monkeypatch.setattr(network, "_windows_best_interface_index", lambda address: 8)

    assert not network.is_eligible_lan_peer(peer)

    monkeypatch.setattr(network, "_windows_best_interface_index", lambda address: 7)

    assert network.is_eligible_lan_peer(peer)


def test_posix_physical_adapters_skip_virtual_names(monkeypatch) -> None:
    monkeypatch.setattr(
        network.psutil,
        "net_if_stats",
        lambda: {
            "en0": object(),
            "lo": object(),
            "docker0": object(),
            "vethabc": object(),
        },
    )
    monkeypatch.setattr(
        network.socket,
        "if_nametoindex",
        lambda name: {"en0": 5, "lo": 1, "docker0": 3, "vethabc": 9}[name],
    )

    assert network._posix_physical_lan_interfaces() == (
        network.PhysicalLanInterface(index=5, name="en0"),
    )


def test_posix_lan_peer_accepts_same_subnet(monkeypatch) -> None:
    monkeypatch.setattr(
        network,
        "eligible_lan_interface_names",
        lambda: frozenset({"wlan0"}),
    )
    monkeypatch.setattr(
        network.psutil,
        "net_if_addrs",
        lambda: {
            "wlan0": [
                SimpleNamespace(
                    family=network.socket.AF_INET,
                    address="192.168.1.10",
                    netmask="255.255.255.0",
                )
            ]
        },
    )

    assert network.is_eligible_lan_peer(IPv4Address("192.168.1.50"), os_name="posix")
    assert not network.is_eligible_lan_peer(IPv4Address("10.0.0.2"), os_name="posix")
