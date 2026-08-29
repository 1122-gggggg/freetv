from __future__ import annotations

import argparse
import json
import os
import socket
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address, IPv4Network, IPv6Address, ip_address
from pathlib import Path
from time import monotonic, sleep
from typing import TypeAlias

import psutil
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.system.network import eligible_lan_interface_names

IPAddress: TypeAlias = IPv4Address | IPv6Address

_CA_CERTIFICATE_NAME = "pc-tv-box-local-ca.cer"
_CA_PRIVATE_KEY_NAME = "pc-tv-box-local-ca-key.pem"
_CERTIFICATE_NAME = "pc-tv-box-controller.cer"
_PRIVATE_KEY_NAME = "pc-tv-box-controller-key.pem"
_CA_VALIDITY = timedelta(days=3650)
_LEAF_VALIDITY = timedelta(days=365)
_RENEWAL_LEEWAY = timedelta(days=1)


class LocalTLSMaterialError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TLSMaterialPaths:
    ca_certificate: Path
    ca_private_key: Path
    certificate: Path
    private_key: Path


def ensure_tls_materials(directory: Path, addresses: Iterable[IPAddress]) -> TLSMaterialPaths:
    """Creates a per-user local CA and a current-address TLS leaf certificate."""
    materials = TLSMaterialPaths(
        ca_certificate=directory / _CA_CERTIFICATE_NAME,
        ca_private_key=directory / _CA_PRIVATE_KEY_NAME,
        certificate=directory / _CERTIFICATE_NAME,
        private_key=directory / _PRIVATE_KEY_NAME,
    )
    certificate_addresses = _certificate_addresses(addresses)
    directory.mkdir(parents=True, exist_ok=True)
    ca_key, ca_certificate = _load_or_create_ca(materials)
    if _leaf_is_usable(materials, ca_certificate, certificate_addresses):
        return materials

    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    leaf_certificate = _build_leaf_certificate(
        ca_key, ca_certificate, leaf_key, certificate_addresses
    )
    _atomic_write(materials.private_key, _serialize_private_key(leaf_key), private=True)
    _atomic_write(
        materials.certificate,
        leaf_certificate.public_bytes(serialization.Encoding.PEM),
        private=False,
    )
    return materials


RFC1918_NETWORKS: tuple[IPv4Network, ...] = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)


def _is_eligible_local_address(address: IPAddress) -> bool:
    if address.is_loopback:
        return True
    if isinstance(address, IPv4Address):
        return any(address in network for network in RFC1918_NETWORKS)
    return False


def local_interface_addresses() -> set[IPAddress]:
    addresses: set[IPAddress] = {IPv4Address("127.0.0.1"), IPv6Address("::1")}
    eligible_names = eligible_lan_interface_names()
    if not eligible_names:
        return addresses
    try:
        interfaces = psutil.net_if_addrs()
    except OSError:
        return addresses
    for interface_name, interface_addresses in interfaces.items():
        if interface_name.casefold() not in eligible_names:
            continue
        for interface_address in interface_addresses:
            if getattr(interface_address, "family", None) not in {socket.AF_INET, socket.AF_INET6}:
                continue
            raw_address = getattr(interface_address, "address", None)
            if not raw_address:
                continue
            try:
                address = ip_address(raw_address.split("%", maxsplit=1)[0])
            except ValueError:
                continue
            if _is_eligible_local_address(address):
                addresses.add(address)
    return addresses


def wait_for_lan_interface_addresses(
    wait_seconds: float,
    *,
    poll_interval_seconds: float = 0.5,
) -> set[IPAddress]:
    if wait_seconds < 0 or poll_interval_seconds <= 0:
        raise ValueError("LAN wait duration must be non-negative and polling must be positive.")
    deadline = monotonic() + wait_seconds
    while True:
        addresses = local_interface_addresses()
        if any(not address.is_loopback for address in addresses):
            return addresses
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise LocalTLSMaterialError(
                "No eligible private LAN address is ready. Connect Ethernet or Wi-Fi and retry."
            )
        sleep(min(poll_interval_seconds, remaining))


def certificate_fingerprint(certificate_path: Path) -> str:
    certificate = _load_ca_certificate(certificate_path)
    fingerprint = certificate.fingerprint(hashes.SHA256()).hex().upper()
    return ":".join(fingerprint[index : index + 2] for index in range(0, len(fingerprint), 2))


def _certificate_addresses(addresses: Iterable[IPAddress]) -> tuple[IPAddress, ...]:
    normalized = {IPv4Address("127.0.0.1"), IPv6Address("::1")}
    for address in addresses:
        if _is_eligible_local_address(address):
            normalized.add(address)
    return tuple(sorted(normalized, key=lambda address: (address.version, address.packed)))


def _load_or_create_ca(materials: TLSMaterialPaths) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    certificate_exists = materials.ca_certificate.is_file()
    key_exists = materials.ca_private_key.is_file()
    if certificate_exists != key_exists:
        raise LocalTLSMaterialError(
            "The local TLS authority files are incomplete. Remove both CA files before retrying."
        )
    if certificate_exists:
        try:
            certificate = _load_ca_certificate(materials.ca_certificate)
            key = serialization.load_pem_private_key(
                materials.ca_private_key.read_bytes(), password=None
            )
        except (OSError, TypeError, ValueError) as error:
            raise LocalTLSMaterialError("The local TLS authority files are invalid.") from error
        if not isinstance(key, rsa.RSAPrivateKey) or not _is_valid_ca(certificate, key):
            raise LocalTLSMaterialError(
                "The local TLS authority files are not a usable PC TV Box CA."
            )
        return key, certificate

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    certificate = _build_ca_certificate(key)
    _atomic_write(materials.ca_private_key, _serialize_private_key(key), private=True)
    _atomic_write(
        materials.ca_certificate,
        certificate.public_bytes(serialization.Encoding.DER),
        private=False,
    )
    return key, certificate


def _load_ca_certificate(certificate_path: Path) -> x509.Certificate:
    raw_certificate = certificate_path.read_bytes()
    try:
        return x509.load_der_x509_certificate(raw_certificate)
    except ValueError:
        return x509.load_pem_x509_certificate(raw_certificate)


def _is_valid_ca(certificate: x509.Certificate, key: rsa.RSAPrivateKey) -> bool:
    if certificate.subject != certificate.issuer or certificate.not_valid_after_utc <= datetime.now(
        UTC
    ):
        return False
    try:
        basic_constraints = certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
    except x509.ExtensionNotFound:
        return False
    if (
        not basic_constraints.ca
        or certificate.public_key().public_numbers() != key.public_key().public_numbers()
    ):
        return False
    try:
        key.public_key().verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            padding.PKCS1v15(),
            certificate.signature_hash_algorithm,
        )
    except InvalidSignature:
        return False
    return True


def _leaf_is_usable(
    materials: TLSMaterialPaths,
    ca_certificate: x509.Certificate,
    addresses: tuple[IPAddress, ...],
) -> bool:
    if not materials.certificate.is_file() or not materials.private_key.is_file():
        return False
    try:
        certificate = x509.load_pem_x509_certificate(materials.certificate.read_bytes())
        key = serialization.load_pem_private_key(materials.private_key.read_bytes(), password=None)
        subject_alternative_names = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        certificate_addresses = set(subject_alternative_names.get_values_for_type(x509.IPAddress))
        certificate_dns_names = set(subject_alternative_names.get_values_for_type(x509.DNSName))
    except (OSError, TypeError, ValueError, x509.ExtensionNotFound):
        return False
    if not isinstance(key, rsa.RSAPrivateKey):
        return False
    if certificate.issuer != ca_certificate.subject:
        return False
    if certificate.not_valid_after_utc <= datetime.now(UTC) + _RENEWAL_LEEWAY:
        return False
    if certificate_addresses != set(addresses) or certificate_dns_names != {"localhost"}:
        return False
    if certificate.public_key().public_numbers() != key.public_key().public_numbers():
        return False
    try:
        ca_certificate.public_key().verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            padding.PKCS1v15(),
            certificate.signature_hash_algorithm,
        )
    except InvalidSignature:
        return False
    return True


def _build_ca_certificate(key: rsa.RSAPrivateKey) -> x509.Certificate:
    now = datetime.now(UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PC TV Box Local CA")])
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + _CA_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )


def _build_leaf_certificate(
    ca_key: rsa.RSAPrivateKey,
    ca_certificate: x509.Certificate,
    leaf_key: rsa.RSAPrivateKey,
    addresses: tuple[IPAddress, ...],
) -> x509.Certificate:
    now = datetime.now(UTC)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PC TV Box Controller")])
    authority_key_identifier = x509.AuthorityKeyIdentifier.from_issuer_public_key(
        ca_key.public_key()
    )
    return (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(ca_certificate.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + _LEAF_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), *(x509.IPAddress(address) for address in addresses)]
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False
        )
        .add_extension(authority_key_identifier, critical=False)
        .sign(ca_key, hashes.SHA256())
    )


def _serialize_private_key(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _atomic_write(path: Path, content: bytes, *, private: bool) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        if private:
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create local PC TV Box TLS material.")
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument(
        "--wait-for-lan-seconds",
        type=float,
        help="Wait up to this many seconds for an eligible private LAN address.",
    )
    arguments = parser.parse_args()
    try:
        addresses = (
            local_interface_addresses()
            if arguments.wait_for_lan_seconds is None
            else wait_for_lan_interface_addresses(arguments.wait_for_lan_seconds)
        )
    except (LocalTLSMaterialError, ValueError) as error:
        parser.error(str(error))
    materials = ensure_tls_materials(arguments.directory, addresses)
    print(
        json.dumps(
            {
                "ca_certificate": str(materials.ca_certificate.resolve()),
                "certificate": str(materials.certificate.resolve()),
                "private_key": str(materials.private_key.resolve()),
                "ca_sha256": certificate_fingerprint(materials.ca_certificate),
                "addresses": [str(address) for address in _certificate_addresses(addresses)],
            }
        )
    )


if __name__ == "__main__":
    main()
