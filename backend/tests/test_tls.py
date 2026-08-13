from __future__ import annotations

import ssl
from ipaddress import IPv4Address

from cryptography import x509

from app.security.tls import ensure_tls_materials


def certificate_san_entries(certificate_path) -> set[tuple[str, str]]:
    decoded = ssl._ssl._test_decode_cert(str(certificate_path))
    return set(decoded["subjectAltName"])


def test_tls_materials_issue_a_local_ca_and_ip_san_leaf_certificate(tmp_path) -> None:
    materials = ensure_tls_materials(tmp_path / "tls", {IPv4Address("192.0.2.44")})

    assert materials.ca_certificate.is_file()
    assert materials.ca_private_key.is_file()
    assert materials.certificate.is_file()
    assert materials.private_key.is_file()
    assert ("IP Address", "192.0.2.44") in certificate_san_entries(materials.certificate)
    assert ("IP Address", "127.0.0.1") in certificate_san_entries(materials.certificate)
    assert ("DNS", "localhost") in certificate_san_entries(materials.certificate)


def test_tls_materials_export_the_local_ca_as_a_windows_installable_der_certificate(
    tmp_path,
) -> None:
    materials = ensure_tls_materials(tmp_path / "tls", {IPv4Address("192.0.2.44")})

    certificate = x509.load_der_x509_certificate(materials.ca_certificate.read_bytes())

    assert certificate.subject == certificate.issuer


def test_tls_materials_reuse_the_local_ca_and_replace_leaf_for_new_ip_addresses(tmp_path) -> None:
    directory = tmp_path / "tls"
    initial = ensure_tls_materials(directory, {IPv4Address("192.0.2.44")})
    initial_ca = initial.ca_certificate.read_bytes()
    initial_leaf = initial.certificate.read_bytes()

    reused = ensure_tls_materials(directory, {IPv4Address("192.0.2.44")})
    reused_leaf = reused.certificate.read_bytes()
    rotated = ensure_tls_materials(directory, {IPv4Address("192.0.2.45")})

    assert reused_leaf == initial_leaf
    assert rotated.ca_certificate.read_bytes() == initial_ca
    assert rotated.certificate.read_bytes() != initial_leaf
    assert ("IP Address", "192.0.2.45") in certificate_san_entries(rotated.certificate)
