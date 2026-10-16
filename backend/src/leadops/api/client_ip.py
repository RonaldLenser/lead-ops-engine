"""Which IP address made this request?

The socket peer is the only address the server can verify. Behind a reverse
proxy (Caddy) the peer is the proxy, and the real client is in
X-Forwarded-For. But any client can send that header, so it is trusted only
when the peer itself is a configured proxy (TRUSTED_PROXY_CIDRS).

When trusted, X-Forwarded-For is read RIGHT to LEFT. Each proxy appends the
address it received the request from, so the rightmost entries were written
by our proxies and the leftmost may be invented by the client. The first
entry that is not one of our proxies is the client.

Default: no trusted proxies, so the header is ignored completely.
"""

from collections.abc import Sequence
from ipaddress import IPv4Network, IPv6Network, ip_address

from starlette.requests import Request

FORWARDED_FOR_HEADER = "X-Forwarded-For"
UNKNOWN_CLIENT = "unknown"

Network = IPv4Network | IPv6Network


def _is_trusted(address: str, trusted: Sequence[Network]) -> bool:
    try:
        parsed = ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in trusted)


def resolve_client_ip(
    peer: str | None, forwarded_for: str | None, trusted: Sequence[Network]
) -> str:
    if peer is None:
        return UNKNOWN_CLIENT
    if not trusted or not forwarded_for or not _is_trusted(peer, trusted):
        return peer
    hops = [hop.strip() for hop in forwarded_for.split(",")]
    for hop in reversed(hops):
        try:
            ip_address(hop)
        except ValueError:
            # Malformed entry: stop trusting the chain and fall back to the peer.
            return peer
        if not _is_trusted(hop, trusted):
            return hop
    # Every hop is one of our proxies: the leftmost is the best we know.
    return hops[0]


def client_ip(request: Request, trusted: Sequence[Network]) -> str:
    peer = request.client.host if request.client else None
    return resolve_client_ip(peer, request.headers.get(FORWARDED_FOR_HEADER), trusted)
