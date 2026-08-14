from __future__ import annotations

import ssl
import socket
from types import SimpleNamespace
from ipaddress import IPv4Address, IPv6Address, ip_address

import psutil
from cryptography import x509

from app.security import tls
from app.security.tls import ensure_tls_materials, local_interface_addresses


def certificate_san_entries(certificate_path) -> set[tuple[str, str]]:
    decoded = ssl._ssl._test_decode_cert(str(certificate_path))
    entries: set[tuple[str, str]] = set()
    for name, value in decoded["subjectAltName"]:
        if name == "IP Address":
            try:
                entries.add((name, str(ip_address(value))))
                continue
            except ValueError:
                pass
        entries.add((name, value))
    return entries


def test_tls_materials_issue_a_local_ca_and_ip_san_leaf_certificate(tmp_path) -> None:
    materials = ensure_tls_materials(tmp_path / "tls", {IPv4Address("192.168.1.44")})

    assert materials.ca_certificate.is_file()
    assert materials.ca_private_key.is_file()
    assert materials.certificate.is_file()
    assert materials.private_key.is_file()
    assert ("IP Address", "192.168.1.44") in certificate_san_entries(materials.certificate)
    assert ("IP Address", "127.0.0.1") in certificate_san_entries(materials.certificate)
    assert ("DNS", "localhost") in certificate_san_entries(materials.certificate)


def test_tls_materials_export_the_local_ca_as_a_windows_installable_der_certificate(
    tmp_path,
) -> None:
    materials = ensure_tls_materials(tmp_path / "tls", {IPv4Address("192.168.1.44")})

    certificate = x509.load_der_x509_certificate(materials.ca_certificate.read_bytes())

    assert certificate.subject == certificate.issuer


def test_tls_materials_reuse_the_local_ca_and_replace_leaf_for_new_ip_addresses(tmp_path) -> None:
    directory = tmp_path / "tls"
    initial = ensure_tls_materials(directory, {IPv4Address("192.168.1.44")})
    initial_ca = initial.ca_certificate.read_bytes()
    initial_leaf = initial.certificate.read_bytes()

    reused = ensure_tls_materials(directory, {IPv4Address("192.168.1.44")})
    reused_leaf = reused.certificate.read_bytes()
    rotated = ensure_tls_materials(directory, {IPv4Address("192.168.1.45")})

    assert reused_leaf == initial_leaf
    assert rotated.ca_certificate.read_bytes() == initial_ca
    assert rotated.certificate.read_bytes() != initial_leaf
    assert ("IP Address", "192.168.1.45") in certificate_san_entries(rotated.certificate)



def test_tls_materials_rotate_the_leaf_when_a_lan_address_is_removed(tmp_path) -> None:
    directory = tmp_path / "tls"
    initial = ensure_tls_materials(
        directory,
        {IPv4Address("192.168.1.44"), IPv4Address("192.168.1.45")},
    )
    initial_leaf = initial.certificate.read_bytes()

    rotated = ensure_tls_materials(directory, {IPv4Address("192.168.1.44")})

    assert rotated.certificate.read_bytes() != initial_leaf
    san = certificate_san_entries(rotated.certificate)
    assert ("IP Address", "192.168.1.44") in san
    assert ("IP Address", "192.168.1.45") not in san

def test_tls_materials_filter_san_entries_to_loopback_and_eligible_private_addresses(
    tmp_path,
) -> None:
    addresses = {
        IPv4Address("192.168.1.50"),
        IPv4Address("10.0.0.1"),
        IPv4Address("203.0.113.1"),
        IPv4Address("8.8.8.8"),
        IPv4Address("169.254.1.1"),
        IPv6Address("2001:db8::1"),
        IPv6Address("fe80::1"),
        IPv4Address("127.0.0.1"),
        IPv6Address("::1"),
    }
    materials = ensure_tls_materials(tmp_path / "tls", addresses)
    san = certificate_san_entries(materials.certificate)

    assert ("DNS", "localhost") in san
    assert ("IP Address", "127.0.0.1") in san
    assert ("IP Address", "::1") in san
    assert ("IP Address", "192.168.1.50") in san
    assert ("IP Address", "10.0.0.1") in san
    assert ("IP Address", "203.0.113.1") not in san
    assert ("IP Address", "8.8.8.8") not in san
    assert ("IP Address", "169.254.1.1") not in san
    assert ("IP Address", "2001:db8::1") not in san
    assert ("IP Address", "fe80::1") not in san


def test_local_interface_addresses_excludes_virtual_adapters(monkeypatch) -> None:
    mock_interfaces = {
        "Wi-Fi": [SimpleNamespace(family=socket.AF_INET, address="192.168.1.10")],
        "vEthernet (WSL)": [SimpleNamespace(family=socket.AF_INET, address="172.20.0.1")],
        "Public Ethernet": [SimpleNamespace(family=socket.AF_INET, address="203.0.113.5")],
        "lo": [SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")],
    }
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: mock_interfaces)
    monkeypatch.setattr(tls, "eligible_lan_interface_names", lambda: frozenset({"wi-fi"}))

    addresses = local_interface_addresses()
    assert addresses == {
        IPv4Address("127.0.0.1"),
        IPv6Address("::1"),
        IPv4Address("192.168.1.10"),
    }
