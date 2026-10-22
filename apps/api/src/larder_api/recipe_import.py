"""Fetching a recipe page for import (POST /recipes/import/read), carefully: the server fetches
a URL a user typed, so it must not become a way to reach anything private.

- http and https only, default ports only, no user:password@ in the URL.
- Every address the host resolves to must be public (no loopback, private, link-local,
  reserved or multicast ranges, nor IPv6 forms that carry one: mapped, NAT64, 6to4, Teredo);
  checked again for each redirect (at most 3).
- The connection goes to the address that was checked, not to a fresh lookup of the name, so
  DNS can't answer "public" for the check and "private" for the connection (rebinding). The
  name still goes in the Host header and TLS SNI, and certificates are checked against it.
- 10 s in total, at most 2 MB read (after decompression, counted as it inflates, so a small
  compressed reply can't expand into a huge one), HTML only, no cookies, a plain user agent.
"""

import asyncio
import ipaddress
import socket
import zlib
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from larder_core.recipe_import import ImportedRecipe, find_recipe

__all__ = ["ImportError_", "fetch_recipe", "public_address"]

MAX_BYTES = 2_000_000
TIMEOUT_S = 10.0
MAX_REDIRECTS = 3
USER_AGENT = "Mealwright recipe import (+https://github.com/edanbro/Dietbro)"


class ImportError_(Exception):
    """Why a page couldn't be imported, in words for the user."""


_NAT64 = ipaddress.ip_network("64:ff9b::/96")
# zlib with 32 added to the window bits reads both gzip and zlib ("deflate") streams.
_INFLATE = {
    "gzip": 32 + zlib.MAX_WBITS,
    "x-gzip": 32 + zlib.MAX_WBITS,
    "deflate": 32 + zlib.MAX_WBITS,
}


def _global(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return address.is_global and not address.is_multicast


def public_address(ip: str) -> bool:
    address = ipaddress.ip_address(ip)
    if isinstance(address, ipaddress.IPv4Address):
        return _global(address)
    if address.ipv4_mapped is not None:
        return _global(address.ipv4_mapped)
    embedded = address.sixtofour or (address.teredo[1] if address.teredo else None)
    if address in _NAT64:
        embedded = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    if embedded is not None and not _global(embedded):
        return False
    return _global(address)


async def resolve(host: str, port: int) -> set[str]:
    """Every address `host` resolves to (tests replace this)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return {str(info[4][0]) for info in infos}


async def _check(url: str) -> tuple[str, str, str]:
    """(the URL with its host replaced by a checked public address, the Host header, the name
    for TLS), or ImportError_."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ImportError_("Use a web address starting with https://")
    if parts.username or parts.password:
        raise ImportError_("That address can't be used")
    if parts.port not in (None, 80, 443):
        raise ImportError_("That address can't be used")
    try:
        addresses = await resolve(
            parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
        )
    except OSError as e:
        raise ImportError_("Couldn't find that website") from e
    if not addresses or not all(public_address(a) for a in addresses):
        raise ImportError_("That address can't be used")
    address = min(addresses)  # any of them: all are public
    host = f"[{address}]" if ":" in address else address
    if parts.port is not None:
        host += f":{parts.port}"
    pinned = urlunsplit((parts.scheme, host, parts.path or "/", parts.query, ""))
    return pinned, parts.netloc, parts.hostname


async def fetch_page(url: str, client: httpx.AsyncClient) -> str:
    for _ in range(MAX_REDIRECTS + 1):
        pinned, host, name = await _check(url)
        async with client.stream(
            "GET", pinned, headers={"Host": host}, extensions={"sni_hostname": name}
        ) as response:
            if response.is_redirect and (location := response.headers.get("location")):
                url = urljoin(url, location)
                continue
            if response.status_code >= 400:
                raise ImportError_(f"The site answered {response.status_code}")
            kind = response.headers.get("content-type", "")
            if "html" not in kind:
                raise ImportError_("That address isn't a web page")
            coding = response.headers.get("content-encoding", "").strip().lower()
            if coding not in ("", "identity", *_INFLATE):
                raise ImportError_("That page can't be read")
            inflate = zlib.decompressobj(_INFLATE[coding]) if coding in _INFLATE else None
            body = bytearray()
            async for chunk in response.aiter_raw():
                if inflate is None:
                    body += chunk
                else:
                    try:
                        body += inflate.decompress(chunk, MAX_BYTES + 1 - len(body))
                    except zlib.error as e:
                        raise ImportError_("That page can't be read") from e
                    if inflate.unconsumed_tail:
                        raise ImportError_("That page is too big to read")
                if len(body) > MAX_BYTES:
                    raise ImportError_("That page is too big to read")
            return body.decode(response.encoding or "utf-8", errors="replace")
    raise ImportError_("Too many redirects")


async def fetch_recipe(url: str, client: httpx.AsyncClient | None = None) -> ImportedRecipe:
    """The recipe on the page at `url`, or ImportError_ saying why not."""
    own = client is None
    client = client or httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(TIMEOUT_S),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            "Accept-Encoding": "gzip, deflate",  # what fetch_page inflates itself
        },
    )
    try:
        async with asyncio.timeout(TIMEOUT_S):
            page = await fetch_page(url.strip(), client)
    except TimeoutError as e:
        raise ImportError_("The site took too long to answer") from e
    except httpx.HTTPError as e:
        raise ImportError_("Couldn't reach that website") from e
    finally:
        if own:
            await client.aclose()
    recipe = find_recipe(page)
    if recipe is None:
        raise ImportError_(
            "No recipe found on that page. Paste the ingredients and method instead."
        )
    return recipe
