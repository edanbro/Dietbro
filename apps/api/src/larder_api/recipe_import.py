"""Fetching a recipe page for import (POST /recipes/import/read), carefully: the server fetches
a URL a user typed, so it must not become a way to reach anything private.

- http and https only, default ports only, no user:password@ in the URL.
- Every address the host resolves to must be public (no loopback, private, link-local,
  reserved or multicast ranges); checked again for each redirect (at most 3).
- 10 s in total, at most 2 MB read, HTML only, no cookies, a plain user agent.

A name could resolve to a public address when checked and a private one when connected
(DNS rebinding); the window is small and the response is only parsed for JSON-LD, never shown
raw. Behind a proxy that does its own egress filtering this is a second line.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from larder_core.recipe_import import ImportedRecipe, find_recipe

__all__ = ["ImportError_", "fetch_recipe", "public_address"]

MAX_BYTES = 2_000_000
TIMEOUT_S = 10.0
MAX_REDIRECTS = 3
USER_AGENT = "Mealwright recipe import (+https://github.com/edanbro/Dietbro)"


class ImportError_(Exception):
    """Why a page couldn't be imported, in words for the user."""


def public_address(ip: str) -> bool:
    address = ipaddress.ip_address(ip)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


async def resolve(host: str, port: int) -> set[str]:
    """Every address `host` resolves to (tests replace this)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return {str(info[4][0]) for info in infos}


async def _check(url: str) -> None:
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


async def fetch_page(url: str, client: httpx.AsyncClient) -> str:
    for _ in range(MAX_REDIRECTS + 1):
        await _check(url)
        async with client.stream("GET", url) as response:
            if response.is_redirect and (location := response.headers.get("location")):
                url = urljoin(url, location)
                continue
            if response.status_code >= 400:
                raise ImportError_(f"The site answered {response.status_code}")
            kind = response.headers.get("content-type", "")
            if "html" not in kind:
                raise ImportError_("That address isn't a web page")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
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
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
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
