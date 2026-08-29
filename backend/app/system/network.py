from __future__ import annotations

import ctypes
import os
import socket
import subprocess
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from time import monotonic

import psutil

_PHYSICAL_ADAPTER_CACHE_SECONDS = 30.0
_PHYSICAL_ADAPTER_COMMAND = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "Get-NetAdapter -Physical | "
    "Where-Object { [int]$_.NdisPhysicalMedium -in 14, 9 } | "
    'ForEach-Object { "$($_.ifIndex)`t$($_.Name)" }'
)
_VIRTUAL_INTERFACE_PREFIXES = (
    "lo",
    "docker",
    "br-",
    "veth",
    "virbr",
    "cni",
    "flannel",
    "cali",
    "tun",
    "tap",
    "utun",
    "awdl",
    "llw",
    "anpi",
    "vmnet",
    "vboxnet",
    "wg",
    "zt",
    "tailscale",
)
_cached_physical_interfaces: tuple[PhysicalLanInterface, ...] = ()
_cache_valid_until = 0.0


@dataclass(frozen=True, slots=True)
class PhysicalLanInterface:
    index: int
    name: str


class _SockAddrIn(ctypes.Structure):
    _fields_ = [
        ("family", ctypes.c_ushort),
        ("port", ctypes.c_ushort),
        ("address", ctypes.c_ubyte * 4),
        ("zero", ctypes.c_ubyte * 8),
    ]


def physical_lan_interfaces() -> tuple[PhysicalLanInterface, ...]:
    """Returns physical Ethernet/Wi-Fi interfaces, cached briefly."""
    global _cached_physical_interfaces, _cache_valid_until
    now = monotonic()
    if now < _cache_valid_until:
        return _cached_physical_interfaces
    if os.name == "nt":
        _cached_physical_interfaces = _windows_physical_lan_interfaces()
    else:
        _cached_physical_interfaces = _posix_physical_lan_interfaces()
    _cache_valid_until = now + _PHYSICAL_ADAPTER_CACHE_SECONDS
    return _cached_physical_interfaces


def physical_lan_interface_names() -> frozenset[str]:
    return frozenset(interface.name for interface in physical_lan_interfaces())


def eligible_lan_interfaces() -> tuple[PhysicalLanInterface, ...]:
    """Returns cached physical Ethernet/Wi-Fi interfaces whose links are currently up."""
    physical_interfaces = physical_lan_interfaces()
    if not physical_interfaces:
        return ()
    try:
        states = psutil.net_if_stats()
    except OSError:
        return ()
    states_by_name = {name.casefold(): state for name, state in states.items()}
    return tuple(
        interface
        for interface in physical_interfaces
        if bool(getattr(states_by_name.get(interface.name), "isup", False))
    )


def eligible_lan_interface_names() -> frozenset[str]:
    return frozenset(interface.name for interface in eligible_lan_interfaces())


def is_eligible_lan_peer(address: IPv4Address, *, os_name: str = os.name) -> bool:
    """Checks that a peer is reachable over a currently up physical LAN interface."""
    if os_name == "nt":
        interface_index = _windows_best_interface_index(address)
        return interface_index is not None and any(
            interface.index == interface_index for interface in eligible_lan_interfaces()
        )
    return _posix_peer_on_eligible_subnet(address)


def _windows_physical_lan_interfaces() -> tuple[PhysicalLanInterface, ...]:
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _PHYSICAL_ADAPTER_COMMAND,
            ],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if result.returncode != 0:
        return ()

    interfaces: list[PhysicalLanInterface] = []
    for line in result.stdout.splitlines():
        raw_index, separator, raw_name = line.partition("\t")
        if not separator or not (name := raw_name.strip()):
            continue
        try:
            index = int(raw_index)
        except ValueError:
            continue
        if index > 0:
            interfaces.append(PhysicalLanInterface(index=index, name=name.casefold()))
    return tuple(interfaces)


def _windows_best_interface_index(address: IPv4Address) -> int | None:
    if os.name != "nt":
        return None
    try:
        ip_helper = ctypes.WinDLL("iphlpapi", use_last_error=True)
        get_best_interface = ip_helper.GetBestInterfaceEx
        get_best_interface.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        get_best_interface.restype = ctypes.c_ulong
    except (AttributeError, OSError):
        return None

    destination = _SockAddrIn()
    destination.family = socket.AF_INET
    for offset, byte in enumerate(address.packed):
        destination.address[offset] = byte
    interface_index = ctypes.c_ulong()
    if get_best_interface(ctypes.byref(destination), ctypes.byref(interface_index)) != 0:
        return None
    return int(interface_index.value)


def _is_virtual_interface(name: str) -> bool:
    lowered = name.casefold()
    return any(
        lowered == prefix or lowered.startswith(prefix) for prefix in _VIRTUAL_INTERFACE_PREFIXES
    )


def _posix_physical_lan_interfaces() -> tuple[PhysicalLanInterface, ...]:
    try:
        stats = psutil.net_if_stats()
    except OSError:
        return ()
    interfaces: list[PhysicalLanInterface] = []
    for name in stats:
        if _is_virtual_interface(name):
            continue
        try:
            index = socket.if_nametoindex(name)
        except OSError:
            index = len(interfaces) + 1
        if index > 0:
            interfaces.append(PhysicalLanInterface(index=index, name=name.casefold()))
    return tuple(interfaces)


def _posix_peer_on_eligible_subnet(address: IPv4Address) -> bool:
    names = eligible_lan_interface_names()
    if not names:
        return False
    try:
        interfaces = psutil.net_if_addrs()
    except OSError:
        return False
    for interface_name, interface_addresses in interfaces.items():
        if interface_name.casefold() not in names:
            continue
        for interface_address in interface_addresses:
            if getattr(interface_address, "family", None) != socket.AF_INET:
                continue
            raw_address = getattr(interface_address, "address", None)
            if not raw_address:
                continue
            try:
                local = IPv4Address(raw_address.split("%", maxsplit=1)[0])
            except ValueError:
                continue
            raw_netmask = getattr(interface_address, "netmask", None)
            if raw_netmask:
                try:
                    network = IPv4Network(f"{local}/{raw_netmask}", strict=False)
                except ValueError:
                    network = IPv4Network(f"{local}/32", strict=False)
            else:
                network = IPv4Network(f"{local}/32", strict=False)
            if address in network:
                return True
    return False
