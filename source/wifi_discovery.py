"""Authenticated mDNS fallback: only return existing paired devices, never scan."""
import ipaddress
from types import SimpleNamespace

from wifi_unicast import authenticated_identifier

DISCOVERY_TIMEOUT = 4
MAX_ENDPOINTS = 3


def _host(address):
    try:
        host = address.full_ip
        parsed = ipaddress.ip_address(host.split('%', 1)[0])
    except (ValueError, AttributeError, TypeError):
        return None
    if (parsed.is_loopback or parsed.is_multicast or parsed.is_unspecified or
            parsed.is_reserved or not (parsed.is_private or parsed.is_link_local)):
        return None
    return host


def paired_devices(answers, pairs):
    """De-duplicate interfaces/instances by trusted identity, preserving endpoints."""
    candidates = {}
    for answer in answers:
        identifier = authenticated_identifier(answer.properties, pairs)
        if identifier is None:
            continue
        try:
            port = int(answer.port)
        except (ValueError, TypeError):
            continue
        if not 1 <= port <= 65535:
            continue
        for address in answer.addresses:
            host = _host(address)
            if host is not None:
                candidates.setdefault(identifier, set()).add((host, port))
    # Prefer IPv4; IPv6 link-local scope from the receiving interface is retained.
    return [SimpleNamespace(serial=serial, connection_type='Network',
                endpoints=tuple(sorted(endpoints, key=lambda item: (':' in item[0], item)))[:MAX_ENDPOINTS])
            for serial, endpoints in sorted(candidates.items())]


async def discover_paired(timeout=DISCOVERY_TIMEOUT):
    from pymobiledevice3.bonjour import browse_remotepairing
    from pymobiledevice3.pair_records import iter_remote_pair_records_by_identifier

    pairs = list(iter_remote_pair_records_by_identifier())
    if not pairs:
        return []
    answers = await browse_remotepairing(timeout=timeout)
    return paired_devices(answers, pairs)
