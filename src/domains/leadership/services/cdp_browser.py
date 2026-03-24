"""CDP-based browser service for LinkedIn scraping.

Uses Chrome DevTools Protocol via WebSocket to control a Chrome instance
with a loaded extension for DOM extraction and screenshot capture.
Replaces the Playwright-based LinkedInBrowser.

Chrome always runs headed (never headless) for reliable LinkedIn access.
"""

from __future__ import annotations

import base64
import json
import os
import platform
import random
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import structlog
import websocket

from src.domains.leadership.core.profile_parsing import (
    extract_linkedin_profile_url,
)

logger = structlog.get_logger(__name__)

# CDP communication timeout (seconds)
_CDP_TIMEOUT = 30

# Page load timeout (seconds)
_PAGE_LOAD_TIMEOUT = 15

# Time to wait for manual login before giving up (seconds)
_LOGIN_WAIT_TIMEOUT = 120

# Default delay between page navigations (seconds)
_MIN_PAGE_DELAY = 3.0
_MAX_PAGE_DELAY = 6.0

# Number of scroll iterations to load more employee cards
_SCROLL_ITERATIONS = 5

# Delay after each scroll (seconds)
_SCROLL_DELAY = 1.5

# Blocking indicators (same as previous Playwright-based detection)
_CAPTCHA_INDICATORS = [
    "captcha",
    "challenge",
    "security verification",
    "verify you are human",
]
_AUTH_WALL_INDICATORS = [
    "join now",
    "sign in",
    "log in",
    "authwall",
]
_RATE_LIMIT_INDICATORS = [
    "too many requests",
    "rate limit",
]

# Chrome binary search paths by platform
_CHROME_PATHS: dict[str, list[str]] = {
    "linux": [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ],
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "win32": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
}


class CDPBlockedError(Exception):
    """Raised when LinkedIn blocks browser access (CAPTCHA, rate limit, auth wall)."""


class CDPConnectionError(Exception):
    """Raised when unable to connect to Chrome via CDP."""


class CDPSession:
    """WebSocket session for Chrome DevTools Protocol communication."""

    def __init__(self, ws_url: str) -> None:
        self._ws = websocket.create_connection(ws_url, timeout=_CDP_TIMEOUT)
        self._message_id = 0

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a CDP command and return the result."""
        self._message_id += 1
        msg: dict[str, Any] = {"id": self._message_id, "method": method}
        if params:
            msg["params"] = params

        self._ws.send(json.dumps(msg))

        # Read responses until we get our result
        deadline = time.monotonic() + _CDP_TIMEOUT
        while time.monotonic() < deadline:
            raw = self._ws.recv()
            if not raw:
                continue
            response = json.loads(raw)
            if response.get("id") == self._message_id:
                if "error" in response:
                    error_msg = response["error"].get("message", "Unknown CDP error")
                    logger.error("cdp_command_error", method=method, error=error_msg)
                    raise CDPConnectionError(f"CDP error in {method}: {error_msg}")
                return response.get("result", {})

        raise CDPConnectionError(f"CDP timeout waiting for response to {method}")

    def close(self) -> None:
        """Close the WebSocket connection."""
        import contextlib

        with contextlib.suppress(Exception):
            self._ws.close()


def _find_chrome_binary() -> str:
    """Find Chrome/Chromium binary on the system."""
    # Check PATH first
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path

    # Check known paths
    system = platform.system().lower()
    if system == "windows":
        system = "win32"
    paths = _CHROME_PATHS.get(system, [])
    for path in paths:
        if os.path.isfile(path):
            return path

    raise FileNotFoundError(
        "Chrome or Chromium not found. Install Google Chrome or set the path manually."
    )


def _get_debugger_url(port: int) -> str:
    """Get the WebSocket debugger URL from Chrome's CDP endpoint."""
    import requests

    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + 10
    last_error = ""

    while time.monotonic() < deadline:
        try:
            resp = requests.get(url, timeout=5)
            data = resp.json()
            ws_url = data.get("webSocketDebuggerUrl", "")
            if ws_url:
                return ws_url
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.5)

    raise CDPConnectionError(
        f"Could not connect to Chrome debugger on port {port}: {last_error}"
    )


def _get_page_targets(port: int) -> list[dict[str, Any]]:
    """Get all page targets from Chrome's CDP endpoint."""
    import requests

    resp = requests.get(f"http://127.0.0.1:{port}/json", timeout=5)
    targets: list[dict[str, Any]] = resp.json()
    return [t for t in targets if t.get("type") == "page"]


class CDPBrowser:
    """Chrome browser controlled via CDP with extension for LinkedIn scraping.

    Always runs headed (never headless) for reliable LinkedIn interaction.
    Uses a persistent user data directory for session cookie persistence.
    """

    def __init__(
        self,
        profile_dir: str = "data/linkedin_profile",
        port: int = 9222,
        screenshot_dir: str = "docs/screenshots",
    ) -> None:
        self.profile_dir = profile_dir
        self.port = port
        self.screenshot_dir = screenshot_dir
        self._process: subprocess.Popen[bytes] | None = None
        self._session: CDPSession | None = None

        # Ensure directories exist
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        Path(self.screenshot_dir).mkdir(parents=True, exist_ok=True)

    def launch(self) -> None:
        """Launch Chrome with remote debugging and the LinkedIn extension loaded."""
        chrome_path = _find_chrome_binary()
        extension_path = str(Path(__file__).resolve().parents[4] / "chrome_extension")

        if not Path(extension_path).is_dir():
            raise FileNotFoundError(
                f"Chrome extension not found at {extension_path}. "
                "Ensure chrome_extension/ directory exists at repository root."
            )

        args = [
            chrome_path,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={os.path.abspath(self.profile_dir)}",
            f"--load-extension={extension_path}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            # Always headed -- no --headless flag
        ]

        logger.info(
            "cdp_launching_chrome",
            chrome_path=chrome_path,
            port=self.port,
            profile_dir=self.profile_dir,
            extension_path=extension_path,
        )

        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for Chrome to start and connect via CDP
        try:
            ws_url = _get_debugger_url(self.port)
            self._session = CDPSession(ws_url)
            logger.info("cdp_chrome_connected", ws_url=ws_url)
        except Exception as exc:
            self.close()
            raise CDPConnectionError(f"Failed to connect to Chrome: {exc}") from exc

    def close(self) -> None:
        """Close the CDP session and Chrome process."""
        if self._session:
            self._session.close()
            self._session = None
        if self._process:
            import contextlib

            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                with contextlib.suppress(Exception):
                    self._process.kill()
            self._process = None
            logger.info("cdp_chrome_closed")

    @property
    def session(self) -> CDPSession:
        """Get the active CDP session, raising if not connected."""
        if self._session is None:
            raise CDPConnectionError("CDP session not connected. Call launch() first.")
        return self._session

    def navigate(self, url: str) -> None:
        """Navigate the browser to a URL and wait for page load."""
        logger.info("cdp_navigating", url=url)

        # Get the current page target and connect to it
        targets = _get_page_targets(self.port)
        if not targets:
            # Open a new tab
            self.session.send("Target.createTarget", {"url": url})
            time.sleep(2)
            # Reconnect to the new target
            targets = _get_page_targets(self.port)
            if not targets:
                raise CDPConnectionError("No page targets available after creating tab")

        target_ws = targets[0].get("webSocketDebuggerUrl")
        if not target_ws:
            raise CDPConnectionError("No WebSocket URL for page target")

        # Close old session and connect to page target
        if self._session:
            self._session.close()
        self._session = CDPSession(target_ws)

        # Enable necessary CDP domains
        self.session.send("Page.enable")
        self.session.send("Runtime.enable")

        # Navigate
        self.session.send("Page.navigate", {"url": url})

        # Wait for page load
        deadline = time.monotonic() + _PAGE_LOAD_TIMEOUT
        while time.monotonic() < deadline:
            try:
                raw = self.session._ws.recv()
                if raw:
                    event = json.loads(raw)
                    if event.get("method") == "Page.loadEventFired":
                        break
            except websocket.WebSocketTimeoutException:
                break
            except Exception:
                break

        # Additional settle time for dynamic content
        time.sleep(1.5)

    def execute_js(self, expression: str) -> Any:
        """Execute JavaScript in the page context and return the result."""
        result = self.session.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": False,
            },
        )
        value = result.get("result", {}).get("value")
        return value

    def get_page_html(self) -> str:
        """Get the full page HTML."""
        html = self.execute_js("document.documentElement.outerHTML")
        return str(html) if html else ""

    def capture_screenshot(self) -> bytes:
        """Capture a screenshot of the visible page as PNG bytes."""
        result = self.session.send(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True},
        )
        data_b64 = result.get("data", "")
        return base64.b64decode(data_b64)

    def save_screenshot(self, prefix: str) -> str:
        """Capture and save a screenshot, returning the file path."""
        png_bytes = self.capture_screenshot()
        timestamp = int(time.time())
        filename = f"{prefix}_{timestamp}.png"
        filepath = os.path.join(self.screenshot_dir, filename)
        with open(filepath, "wb") as f:
            f.write(png_bytes)
        logger.info("cdp_screenshot_saved", path=filepath, size_bytes=len(png_bytes))
        return filepath

    def scroll_page(self, times: int = _SCROLL_ITERATIONS) -> None:
        """Scroll the page down to load dynamic content."""
        for i in range(times):
            self.execute_js("window.scrollBy(0, 800)")
            time.sleep(_SCROLL_DELAY)
            logger.debug("cdp_scroll_iteration", iteration=i + 1, total=times)

    def scroll_to_top(self) -> None:
        """Scroll back to the top of the page."""
        self.execute_js("window.scrollTo(0, 0)")
        time.sleep(0.5)

    def close_popups(self) -> int:
        """Dismiss LinkedIn popups via the content script."""
        result = self.execute_js("""
            (function() {
                var selectors = [
                    'button[aria-label="Dismiss"]',
                    'button[aria-label="Close"]',
                    'button.msg-overlay-bubble-header__control--close',
                    'button[action-type="DENY"]',
                    '.artdeco-modal__dismiss',
                    '.artdeco-toast-item__dismiss',
                    '#artdeco-global-alert-container button'
                ];
                var closed = 0;
                selectors.forEach(function(sel) {
                    try {
                        document.querySelectorAll(sel).forEach(function(btn) {
                            if (btn.offsetParent !== null) {
                                btn.click();
                                closed++;
                            }
                        });
                    } catch(e) {}
                });
                return closed;
            })()
        """)
        closed = int(result) if result else 0
        if closed > 0:
            logger.debug("cdp_popups_closed", count=closed)
        return closed

    def detect_blocking(self) -> str | None:
        """Detect if LinkedIn is blocking access.

        Returns blocking reason string or None if page is accessible.
        """
        try:
            page_content = self.execute_js("document.body.innerText.toLowerCase()")
            if not page_content:
                page_content = ""
            page_url = self.execute_js("window.location.href") or ""
        except Exception:
            return "page_error"

        page_content = str(page_content).lower()
        page_url = str(page_url).lower()

        # Check CAPTCHA (non-recoverable)
        for indicator in _CAPTCHA_INDICATORS:
            if indicator in page_content:
                logger.warning("cdp_blocked_captcha", indicator=indicator)
                return "captcha"

        # Check rate limit (non-recoverable)
        for indicator in _RATE_LIMIT_INDICATORS:
            if indicator in page_content:
                logger.warning("cdp_blocked_rate_limit", indicator=indicator)
                return "rate_limit"

        # Check auth wall (potentially recoverable via manual login)
        if "authwall" in page_content or "authwall" in page_url:
            logger.warning("cdp_blocked_auth_wall")
            return "auth_wall"

        for indicator in _AUTH_WALL_INDICATORS:
            if (
                indicator in page_content
                and "org-people" not in page_content
                and ("sign in" in page_content or "join now" in page_content)
            ):
                logger.warning("cdp_blocked_auth_wall", indicator=indicator)
                return "auth_wall"

        return None

    def wait_for_login(self, target_url: str) -> None:
        """Wait for user to manually log in via the headed browser.

        Polls every 5 seconds up to _LOGIN_WAIT_TIMEOUT.
        """
        logger.warning(
            "cdp_login_required",
            message="Please log into LinkedIn in the browser window. "
            f"Waiting up to {_LOGIN_WAIT_TIMEOUT}s...",
        )

        start = time.monotonic()
        while time.monotonic() - start < _LOGIN_WAIT_TIMEOUT:
            time.sleep(5)
            try:
                current_url = self.execute_js("window.location.href") or ""
                if "linkedin.com/company" in current_url or "linkedin.com/in/" in current_url:
                    logger.info("cdp_login_detected", url=current_url)
                    return

                page_text = self.execute_js("document.body.innerText.toLowerCase()") or ""
                if "authwall" not in str(page_text).lower():
                    # Auth wall gone, navigate to target
                    self.navigate(target_url)
                    return
            except Exception:
                continue

        raise CDPBlockedError("Login timeout: user did not log in within time limit")

    def delay_between_pages(self) -> None:
        """Random delay between page navigations to avoid rate limiting."""
        delay = random.uniform(_MIN_PAGE_DELAY, _MAX_PAGE_DELAY)
        logger.debug("cdp_page_delay", delay_seconds=round(delay, 1))
        time.sleep(delay)

    # --- High-level extraction methods ---

    def extract_people(
        self,
        company_linkedin_url: str,
    ) -> list[dict[str, str]]:
        """Navigate to LinkedIn company People tab and extract employee cards.

        This method implements the LinkedInBrowserProtocol interface.

        Args:
            company_linkedin_url: LinkedIn company page URL

        Returns:
            List of dicts with keys: name, title, profile_url

        Raises:
            CDPBlockedError: When LinkedIn blocks access
        """
        people_url = company_linkedin_url.rstrip("/") + "/people/"

        logger.info("cdp_extract_people_start", url=people_url)

        self.navigate(people_url)
        self.close_popups()

        # Check for blocking
        blocking = self.detect_blocking()
        if blocking == "auth_wall":
            self.wait_for_login(people_url)
            blocking = self.detect_blocking()

        if blocking:
            raise CDPBlockedError(f"LinkedIn blocked access: {blocking}")

        # Scroll to load employee cards
        self.scroll_page()
        self.close_popups()

        # Extract via JavaScript (same logic as content.js extractCompanyPeopleData)
        raw = self.execute_js("""
            (function() {
                var data = { employees: [] };
                var seen = {};

                var cardSelectors = [
                    'div[class*="org-people-profile-card"]',
                    'li[class*="org-people-profiles-module__profile-card"]',
                    'div[data-test-id="org-people-profile-card"]'
                ];

                var cards = [];
                for (var i = 0; i < cardSelectors.length; i++) {
                    var found = document.querySelectorAll(cardSelectors[i]);
                    if (found.length > 0) { cards = found; break; }
                }

                if (cards.length > 0) {
                    cards.forEach(function(card) {
                        try {
                            var q = card.querySelector.bind(card);
                            var nameEl = q('[class*="profile-card__title"]')
                                || q('[class*="artdeco-entity-lockup__title"]');
                            var subtitleEl = q('[class*="profile-card__subtitle"]')
                                || q('[class*="artdeco-entity-lockup__subtitle"]');
                            var linkEl = q('a[href*="/in/"]');
                            var name = nameEl ? nameEl.innerText.trim() : null;
                            var title = subtitleEl ? subtitleEl.innerText.trim() : '';
                            var pUrl = null;
                            if (linkEl) {
                                var h = linkEl.getAttribute('href') || '';
                                pUrl = h.startsWith('/')
                                    ? 'https://www.linkedin.com' + h.split('?')[0]
                                    : h.split('?')[0];
                            }
                            if (name && pUrl && !seen[pUrl]) {
                                seen[pUrl] = true;
                                data.employees.push({
                                    name: name, title: title, profile_url: pUrl
                                });
                            }
                        } catch(e) {}
                    });
                }

                if (data.employees.length === 0) {
                    var links = document.querySelectorAll('a[href*="/in/"]');
                    links.forEach(function(link) {
                        try {
                            var href = link.getAttribute('href') || '';
                            var fullUrl = href.startsWith('/')
                                ? 'https://www.linkedin.com' + href.split('?')[0]
                                : href.split('?')[0];
                            if (fullUrl && !seen[fullUrl]) {
                                seen[fullUrl] = true;
                                data.employees.push({
                                    name: link.innerText.trim() || 'Unknown',
                                    title: '',
                                    profile_url: fullUrl
                                });
                            }
                        } catch(e) {}
                    });
                }

                return JSON.stringify(data);
            })()
        """)

        people: list[dict[str, str]] = []
        if raw:
            try:
                parsed = json.loads(str(raw))
                for emp in parsed.get("employees", []):
                    profile_url = extract_linkedin_profile_url(emp.get("profile_url", ""))
                    if profile_url and emp.get("name"):
                        people.append({
                            "name": emp["name"],
                            "title": emp.get("title", ""),
                            "profile_url": profile_url,
                        })
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("cdp_people_parse_failed", error=str(exc))

        logger.info("cdp_extract_people_complete", url=people_url, people_found=len(people))
        return people

    def extract_person_profile(self, profile_url: str) -> dict[str, Any]:
        """Navigate to a personal LinkedIn profile and extract data.

        Args:
            profile_url: LinkedIn personal profile URL (linkedin.com/in/...)

        Returns:
            Dict with keys: name, headline, location, about, experience, profile_url

        Raises:
            CDPBlockedError: When LinkedIn blocks access
        """
        logger.info("cdp_extract_person_start", url=profile_url)

        self.navigate(profile_url)
        self.close_popups()

        # Check for blocking
        blocking = self.detect_blocking()
        if blocking == "auth_wall":
            self.wait_for_login(profile_url)
            blocking = self.detect_blocking()

        if blocking:
            raise CDPBlockedError(f"LinkedIn blocked access: {blocking}")

        # Scroll to load experience section
        self.scroll_page(times=3)
        self.close_popups()

        # Extract profile data via JS
        raw = self.execute_js("""
            (function() {
                var data = {};

                var nameEl = document.querySelector('h1.text-heading-xlarge') ||
                    document.querySelector('h1.inline.t-24') ||
                    document.querySelector('.pv-top-card--list h1') ||
                    document.querySelector('h1');
                if (nameEl) data.name = nameEl.innerText.trim();

                var headlineEl = document.querySelector('div.text-body-medium.break-words') ||
                    document.querySelector('.pv-top-card--list .text-body-medium');
                if (headlineEl) data.headline = headlineEl.innerText.trim();

                var locationEl = document.querySelector(
                    'span.text-body-small.inline.t-black--light.break-words');
                if (locationEl) data.location = locationEl.innerText.trim();

                var aboutSection = document.querySelector(
                    '#about ~ div .inline-show-more-text');
                if (aboutSection) data.about = aboutSection.innerText.trim();

                var experienceSection = document.getElementById('experience');
                if (experienceSection) {
                    var container = experienceSection.closest('section');
                    if (container) {
                        var entries = container.querySelectorAll('li.artdeco-list__item');
                        var experience = [];
                        entries.forEach(function(entry) {
                            var titleEl = entry.querySelector('span.mr1.t-bold span') ||
                                entry.querySelector('span.t-bold span') ||
                                entry.querySelector('.t-bold');
                            var companyEl = entry.querySelector('span.t-14.t-normal span') ||
                                entry.querySelector('.t-14.t-normal');
                            var datesEl = entry.querySelector(
                                'span.t-14.t-normal.t-black--light span');
                            var companyLink = entry.querySelector('a[href*="/company/"]');

                            var exp = {};
                            if (titleEl) exp.title = titleEl.innerText.trim();
                            if (companyEl) exp.company = companyEl.innerText.trim();
                            if (datesEl) exp.dates = datesEl.innerText.trim();
                            if (companyLink) {
                                exp.company_linkedin_url = companyLink.href.split('?')[0]
                                    .replace(/\\/+$/, '');
                            }
                            if (Object.keys(exp).length > 0) experience.push(exp);
                        });
                        if (experience.length > 0) data.experience = experience;
                    }
                }

                data.profile_url = window.location.href;
                return JSON.stringify(data);
            })()
        """)

        profile_data: dict[str, Any] = {}
        if raw:
            try:
                profile_data = json.loads(str(raw))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("cdp_profile_parse_failed", error=str(exc))

        logger.info(
            "cdp_extract_person_complete",
            url=profile_url,
            has_name=bool(profile_data.get("name")),
            experience_count=len(profile_data.get("experience", [])),
        )
        return profile_data

    def capture_people_screenshots(
        self,
        company_linkedin_url: str,
        company_id: int,
    ) -> list[str]:
        """Capture multiple screenshots of the People tab by scrolling.

        Returns list of saved screenshot file paths.
        """
        screenshots: list[str] = []
        prefix = f"company_{company_id}_people"

        # Scroll to top first
        self.scroll_to_top()
        time.sleep(1)

        # Capture initial view
        path = self.save_screenshot(f"{prefix}_batch0")
        screenshots.append(path)

        # Scroll and capture additional batches
        for batch in range(1, 4):
            self.execute_js("window.scrollBy(0, 800)")
            time.sleep(_SCROLL_DELAY)
            path = self.save_screenshot(f"{prefix}_batch{batch}")
            screenshots.append(path)

        logger.info(
            "cdp_people_screenshots_captured",
            company_id=company_id,
            screenshot_count=len(screenshots),
        )
        return screenshots

    def capture_profile_screenshot(
        self,
        company_id: int,
        person_name: str,
    ) -> str:
        """Capture a screenshot of the current personal profile page.

        Returns the saved screenshot file path.
        """
        safe_name = person_name.replace(" ", "_").replace("/", "_")[:50]
        prefix = f"company_{company_id}_person_{safe_name}"
        return self.save_screenshot(prefix)
