"""Find a previously paired iPhone by querying its mDNS service at a known LAN IP.

Windows hosts sometimes reach the phone by TCP but receive no multicast mDNS.
The advertised authTag is checked against a local RemotePairing record before
the app contacts the advertised tunnel port.
"""

import asyncio
import ipaddress
import socket


class WirelessDiscoveryError(Exception):
    pass


def authenticated_identifier(properties, pairs):
    """Match an announcement to exactly one existing record; never auto-pair."""
    from pymobiledevice3.remote.tunnel_service import PEER_ALT_IRK_KEY, validate_auth_tag

    advertised_id, auth_tag = properties.get('identifier'), properties.get('authTag')
    if not advertised_id or not auth_tag:
        return None
    matches = set()
    for identifier, _, record in pairs:
        alt_irk = record.get(PEER_ALT_IRK_KEY)
        if not alt_irk:
            continue
        try:
            if validate_auth_tag(alt_irk, advertised_id, auth_tag):
                matches.add(identifier)
        except (ValueError, TypeError):
            # Malformed/untrusted TXT must not prevent other paired adverts.
            continue
    return next(iter(matches)) if len(matches) == 1 else None


def _query(host):
    from pymobiledevice3.bonjour import (
        REMOTEPAIRING_SERVICE_NAME, QTYPE_PTR, build_query, parse_mdns_message,
    )
    packet = build_query(REMOTEPAIRING_SERVICE_NAME, QTYPE_PTR, unicast=True)
    for _ in range(2):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            try:
                sock.sendto(packet, (host, 5353))
                answer, address = sock.recvfrom(16384)
            except socket.timeout:
                continue
            if address[0] == host:
                return parse_mdns_message(answer)
    raise WirelessDiscoveryError('手机地址可填写，但未收到它的无线配对服务回应。请确认 IP 未变化、手机 Wi-Fi 开启且屏幕已解锁。')


def _match(records):
    from pymobiledevice3.bonjour import REMOTEPAIRING_SERVICE_NAME, QTYPE_PTR, QTYPE_SRV, QTYPE_TXT
    from pymobiledevice3.pair_records import iter_remote_pair_records_by_identifier

    targets = {r.get('ptrdname') for r in records
               if r.get('type') == QTYPE_PTR and r.get('name') == REMOTEPAIRING_SERVICE_NAME}
    pairs = list(iter_remote_pair_records_by_identifier())
    matches = set()
    for target in targets:
        srv = next((r for r in records if r.get('type') == QTYPE_SRV and r.get('name') == target), None)
        txt = next((r for r in records if r.get('type') == QTYPE_TXT and r.get('name') == target), None)
        if not srv or not txt:
            continue
        try:
            port = int(srv.get('port') or 0)
        except (ValueError, TypeError):
            continue
        if not 1 <= port <= 65535:
            continue
        identifier = authenticated_identifier(txt.get('txt') or {}, pairs)
        if identifier is not None:
            matches.add((identifier, port))
    if len(matches) != 1:
        raise WirelessDiscoveryError('已收到手机的无线公告，但未能与本机唯一的已配对手机匹配。请重新用 USB 点击无线准备。')
    return next(iter(matches))


async def discover(host):
    try:
        address = ipaddress.IPv4Address(host.strip())
    except (ValueError, AttributeError):
        raise WirelessDiscoveryError('请填写 iPhone 当前 Wi-Fi 的 IPv4 地址。') from None
    if address.is_loopback or address.is_multicast or address.is_unspecified:
        raise WirelessDiscoveryError('请填写 iPhone 当前 Wi-Fi 的有效 IPv4 地址。')
    records = await asyncio.to_thread(_query, str(address))
    return _match(records)
