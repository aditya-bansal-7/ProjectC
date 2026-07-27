"""
HTTP client wrapper for Project B REST API.
"""

from __future__ import annotations

import logging
from typing import Optional
import requests

from config import settings

logger = logging.getLogger(__name__)

TIMEOUT_SHORT = 10
TIMEOUT_LONG = 30


class ProjectBClient:
    def __init__(self):
        self.base = settings.PROJECT_B_URL
        self._secret = settings.PROJECT_B_SECRET

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _headers(self, auth: bool = False) -> dict:
        h = {"Content-Type": "application/json"}
        if auth and self._secret:
            h["Authorization"] = f"Bearer {self._secret}"
        return h

    def _get(self, path: str, **kwargs) -> dict:
        url = f"{self.base}{path}"
        resp = requests.get(url, headers=self._headers(), timeout=TIMEOUT_SHORT, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict = None, auth: bool = False) -> dict:
        url = f"{self.base}{path}"
        resp = requests.post(
            url,
            json=data or {},
            headers=self._headers(auth=auth),
            timeout=TIMEOUT_LONG,
        )
        resp.raise_for_status()
        return resp.json()

    def _absolute_url(self, url: str) -> str:
        """Return *url* as a fully-qualified URL.

        Project B sometimes returns a relative path (e.g. '/browser/admin-123/')
        instead of a full URL.  Telegram InlineKeyboardButton rejects relative
        URLs, so we prepend self.base whenever the value starts with '/'.
        """
        if url and url.startswith("/"):
            # Strip any trailing slash from base to avoid double-slash
            return self.base.rstrip("/") + url
        return url

    # -------------------------------------------------------------------------
    # Browser / Chrome profile endpoints
    # -------------------------------------------------------------------------

    def ping(self) -> bool:
        """Health check — returns True if Project B is reachable."""
        try:
            resp = requests.get(f"{self.base}/ping", timeout=5)
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"[ProjectB] ping failed: {e}")
            return False

    def create_chrome_profile(self, chrome_id: Optional[str] = None) -> dict:
        """
        POST /browser/create
        Returns: {chromeId, loginUrl, url, success, running}

        The ``url`` and ``loginUrl`` fields are normalised to absolute URLs
        before being returned so callers never receive a bare relative path.
        """
        payload = {}
        if chrome_id:
            payload["chromeId"] = chrome_id
        try:
            result = self._post("/browser/create", payload)
            for key in ("url", "loginUrl"):
                if key in result:
                    result[key] = self._absolute_url(result[key])
            return result
        except Exception as e:
            logger.error(f"[ProjectB] create_chrome_profile error: {e}")
            raise

    def start_browser(self, chrome_id: str) -> dict:
        """
        POST /browser/:chromeId/start
        Returns: {chromeId, loginUrl, url, running}

        The ``url`` and ``loginUrl`` fields are normalised to absolute URLs
        before being returned so callers never receive a bare relative path.
        """
        try:
            result = self._post(f"/browser/{chrome_id}/start")
            for key in ("url", "loginUrl"):
                if key in result:
                    result[key] = self._absolute_url(result[key])
            return result
        except Exception as e:
            logger.error(f"[ProjectB] start_browser({chrome_id}) error: {e}")
            raise

    def stop_browser(self, chrome_id: str) -> dict:
        """POST /browser/:chromeId/stop"""
        try:
            return self._post(f"/browser/{chrome_id}/stop")
        except Exception as e:
            logger.error(f"[ProjectB] stop_browser({chrome_id}) error: {e}")
            raise

    def get_browser_status(self, chrome_id: str) -> dict:
        """
        GET /browser/status/:chromeId
        Returns: {chromeId, running, state, loggedIn, ...}
        """
        try:
            return self._get(f"/browser/status/{chrome_id}")
        except Exception as e:
            logger.error(f"[ProjectB] get_browser_status({chrome_id}) error: {e}")
            return {"running": False, "loggedIn": False, "error": str(e)}

    def list_browsers(self) -> list:
        """GET /browser/list"""
        try:
            return self._get("/browser/list")
        except Exception as e:
            logger.error(f"[ProjectB] list_browsers error: {e}")
            return []

    def delete_browser_profile(self, chrome_id: str) -> dict:
        """DELETE /browser/:chromeId"""
        try:
            url = f"{self.base}/browser/{chrome_id}"
            resp = requests.delete(url, headers=self._headers(), timeout=TIMEOUT_SHORT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[ProjectB] delete_browser_profile({chrome_id}) error: {e}")
            raise

    # -------------------------------------------------------------------------
    # Retweet endpoints
    # -------------------------------------------------------------------------

    def retweet(self, chrome_id: str, tweet_url: str) -> dict:
        """
        POST /retweet
        Returns: {queued, chromeId, count, items, queue}
        """
        payload = {"chromeId": chrome_id, "url": tweet_url}
        try:
            return self._post("/retweet", payload, auth=True)
        except requests.HTTPError as e:
            logger.error(f"[ProjectB] retweet HTTP error: {e}")
            raise
        except Exception as e:
            logger.error(f"[ProjectB] retweet error: {e}")
            raise

    def bulk_retweet(self, chrome_id: str, urls: list[str]) -> dict:
        """
        POST /retweet with x_urls array
        """
        payload = {"chromeId": chrome_id, "x_urls": urls}
        try:
            return self._post("/retweet", payload, auth=True)
        except Exception as e:
            logger.error(f"[ProjectB] bulk_retweet error: {e}")
            raise

    def is_logged_in(self, chrome_id: str) -> bool:
        """Quick check — returns True if the browser profile is logged into X."""
        status = self.get_browser_status(chrome_id)
        return bool(status.get("loggedIn", False))


# Singleton
project_b = ProjectBClient()
