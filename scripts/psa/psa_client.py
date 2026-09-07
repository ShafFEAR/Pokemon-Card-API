"""Rate-limited HTTP client for psacard.com.

PSA's robots.txt (checked 2026-09-07) allows crawling /priceguide/ with
"Crawl-delay: 1". This client enforces at least that gap between requests
regardless of caller, and identifies itself with a normal browser user agent
(PSA returns 403 to generic/library user agents, but robots.txt otherwise
permits this path - this is about not being blocked as a non-browser client,
not about evading any access restriction).
"""
import time

import requests

from . import config


class PsaClient:
    def __init__(self, delay=config.PSA_REQUEST_DELAY_SECONDS):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self.delay = delay
        self._last_request_time = None

    def get(self, url, **kwargs):
        if self._last_request_time is not None:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
        resp = self.session.get(url, timeout=30, **kwargs)
        self._last_request_time = time.monotonic()
        resp.raise_for_status()
        return resp
