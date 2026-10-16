from ipaddress import ip_network

import pytest

from leadops.api.client_ip import resolve_client_ip

PROXY_NET = [ip_network("172.18.0.0/16")]


def test_header_is_ignored_when_no_proxies_are_trusted() -> None:
    assert resolve_client_ip("203.0.113.7", "1.2.3.4", []) == "203.0.113.7"


def test_spoofed_header_from_an_untrusted_peer_is_ignored() -> None:
    assert resolve_client_ip("203.0.113.7", "1.2.3.4", PROXY_NET) == "203.0.113.7"


def test_trusted_proxy_header_gives_the_client() -> None:
    assert resolve_client_ip("172.18.0.5", "198.51.100.9", PROXY_NET) == "198.51.100.9"


def test_rightmost_untrusted_entry_wins_over_a_spoofed_leftmost_entry() -> None:
    # Client sent "X-Forwarded-For: 1.2.3.4"; our proxy appended the real address.
    assert resolve_client_ip("172.18.0.5", "1.2.3.4, 198.51.100.9", PROXY_NET) == "198.51.100.9"


def test_chains_of_trusted_proxies_are_skipped() -> None:
    assert resolve_client_ip("172.18.0.5", "198.51.100.9, 172.18.0.9", PROXY_NET) == "198.51.100.9"


@pytest.mark.parametrize("header", ["not-an-ip", "198.51.100.9, garbage", ""])
def test_malformed_headers_fall_back_to_the_peer(header: str) -> None:
    assert resolve_client_ip("172.18.0.5", header, PROXY_NET) == "172.18.0.5"


def test_ipv6_proxies_and_clients_work() -> None:
    assert resolve_client_ip("fd00::1", "2001:db8::42", [ip_network("fd00::/8")]) == "2001:db8::42"


def test_missing_peer_is_reported_as_unknown() -> None:
    assert resolve_client_ip(None, "1.2.3.4", PROXY_NET) == "unknown"
