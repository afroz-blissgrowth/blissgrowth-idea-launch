"""Shared HTTP helper (stdlib only).

Importing this module makes Python try IPv4 addresses first. On some networks (this Mac
included) the IPv6 route silently hangs, urllib waits out the whole timeout on it, and
`curl` works while Python does not.
"""
from __future__ import annotations

import socket
import urllib.error
import urllib.request

_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_first(*args, **kwargs):
    res = _orig_getaddrinfo(*args, **kwargs)
    return sorted(res, key=lambda r: r[0] != socket.AF_INET)


socket.getaddrinfo = _ipv4_first


def fetch(method, url, headers=None, data=None, timeout=30):
    """Return (status, lowercase-header dict, body bytes). HTTP errors return their status, not raise."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
