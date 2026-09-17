from __future__ import annotations

import urllib.request
from urllib.parse import urlsplit


class ReleaseRedirectError(RuntimeError):
    pass


def _github_storage_host(hostname: str | None) -> bool:
    value = (hostname or "").casefold()
    return value.endswith(".githubusercontent.com") and value != ".githubusercontent.com"


class _ReleaseRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, expected_github_url: str):
        super().__init__()
        parsed = urlsplit(expected_github_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.username
            or parsed.password
            or not parsed.path.startswith("/Faysk/tda/releases/download/")
        ):
            raise ReleaseRedirectError("RELEASE_EXPECTED_URL_INVALID")
        self.expected_github_url = expected_github_url
        self.reached_github = False

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        current = urlsplit(req.full_url)
        target = urlsplit(newurl)
        if target.scheme != "https" or target.username or target.password:
            raise ReleaseRedirectError("RELEASE_REDIRECT_REJECTED")

        if not self.reached_github:
            if newurl != self.expected_github_url:
                raise ReleaseRedirectError("RELEASE_REDIRECT_REJECTED")
            self.reached_github = True
        else:
            current_is_github = current.scheme == "https" and current.hostname == "github.com"
            current_is_storage = current.scheme == "https" and _github_storage_host(current.hostname)
            target_is_storage = _github_storage_host(target.hostname)
            if not (target_is_storage and (current_is_github or current_is_storage)):
                raise ReleaseRedirectError("RELEASE_REDIRECT_REJECTED")

        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_verified_release(
    request: urllib.request.Request,
    *,
    expected_github_url: str,
    timeout: float,
):
    """Open a TDA release while constraining every redirect in the chain.

    Stable downloads normally start at dnd.faysk.dev and must first redirect to
    the exact GitHub asset. Runtime RC discovery already resolves an immutable
    exact GitHub asset, so that direct form is also accepted; its first redirect
    must then be GitHub's official release-asset storage host.
    """
    handler = _ReleaseRedirectHandler(expected_github_url)
    if request.full_url == expected_github_url:
        handler.reached_github = True
    opener = urllib.request.build_opener(handler)
    return opener.open(request, timeout=timeout)
