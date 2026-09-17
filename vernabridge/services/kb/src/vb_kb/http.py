"""One shared way to talk HTTP, so every importer behaves politely.

Rules encoded here (see DECISIONS.md ADR-004 and the GBIF etiquette notes):
- identify ourselves with the repo URL, never anyone's personal data
- time out instead of hanging forever
- back off and retry on temporary server errors (5xx), fail fast on our own
  mistakes (4xx)
"""

from __future__ import annotations

import time

import httpx

# The one and only client identity. Bump the version with the package.
USER_AGENT = "VernaBridge/0.1 (+https://github.com/thesamotar/GB_Submission)"

_RETRYABLE = {429, 500, 502, 503, 504}


def make_client(timeout_seconds: float = 60.0) -> httpx.Client:
    """Create an HTTP client with our identity and sane timeouts."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=timeout_seconds,
        follow_redirects=True,
    )


def get_with_retry(
    client: httpx.Client,
    url: str,
    params: dict[str, str] | None = None,
    max_attempts: int = 4,
) -> httpx.Response:
    """GET a URL, retrying with growing pauses on temporary failures.

    Waits 2s, 4s, 8s between attempts. Anything that is clearly our fault
    (404, 400, ...) raises immediately — retrying would just hammer the server.
    """
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            response = client.get(url, params=params)
            if response.status_code in _RETRYABLE:
                raise httpx.HTTPStatusError(
                    f"retryable status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.HTTPStatusError) as error:
            # Non-retryable HTTP errors (4xx except 429) get raised right away.
            if (
                isinstance(error, httpx.HTTPStatusError)
                and error.response.status_code not in _RETRYABLE
            ):
                raise
            last_error = error
            if attempt < max_attempts - 1:
                time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"giving up on {url} after {max_attempts} attempts") from last_error
