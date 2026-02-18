"""Headed Playwright browser service for LinkedIn People tab scraping."""

from __future__ import annotations

import time
from typing import Any

import structlog

from src.domains.leadership.core.profile_parsing import (
    extract_linkedin_profile_url,
)

logger = structlog.get_logger(__name__)

# Selectors for LinkedIn People tab elements (fragile by nature)
_PEOPLE_CARD_SELECTOR = (
    'div[class*="org-people-profile-card"], '
    'li[class*="org-people-profiles-module__profile-card"], '
    'div[data-test-id="org-people-profile-card"]'
)
_CARD_NAME_SELECTOR = (
    '[class*="profile-card__title"], '
    '[class*="org-people-profile-card__profile-title"], '
    '[class*="artdeco-entity-lockup__title"]'
)
_CARD_SUBTITLE_SELECTOR = (
    '[class*="profile-card__subtitle"], '
    '[class*="org-people-profile-card__subtitle"], '
    '[class*="artdeco-entity-lockup__subtitle"]'
)
_CARD_LINK_SELECTOR = 'a[href*="/in/"]'

# Blocking indicators
_CAPTCHA_INDICATORS = [
    "captcha",
    "challenge",
    "security verification",
    "verify you are human",
]
_AUTH_WALL_INDICATORS = [
    "join now",
    "sign in",
    "Log in",
    "authwall",
]
_RATE_LIMIT_INDICATORS = [
    "too many requests",
    "rate limit",
]

# Page load timeout in milliseconds
_PAGE_TIMEOUT_MS = 15000

# Time to wait for manual login before giving up (seconds)
_LOGIN_WAIT_TIMEOUT = 120


class LinkedInBlockedError(Exception):
    """Raised when LinkedIn blocks browser access (CAPTCHA, rate limit)."""


class LinkedInBrowser:
    """Headed Playwright browser for LinkedIn People tab extraction.

    Uses a persistent browser profile to maintain LinkedIn login session.
    """

    def __init__(
        self,
        headless: bool = False,
        profile_dir: str = "data/linkedin_profile",
    ) -> None:
        self.headless = headless
        self.profile_dir = profile_dir

    def extract_people(
        self,
        company_linkedin_url: str,
    ) -> list[dict[str, str]]:
        """Navigate to LinkedIn company People tab and extract employee cards.

        Args:
            company_linkedin_url: LinkedIn company page URL
                (e.g., https://www.linkedin.com/company/acme)

        Returns:
            List of dicts with keys: name, title, profile_url

        Raises:
            LinkedInBlockedError: When LinkedIn blocks access (CAPTCHA, rate limit)
        """
        from playwright.sync_api import sync_playwright

        people_url = company_linkedin_url.rstrip("/") + "/people/"

        logger.info(
            "linkedin_browser_starting",
            url=people_url,
            headless=self.headless,
        )

        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )

            try:
                page = context.new_page()
                page.goto(people_url, timeout=_PAGE_TIMEOUT_MS)
                page.wait_for_load_state("domcontentloaded", timeout=_PAGE_TIMEOUT_MS)

                # Check for blocking
                blocking_reason = self._detect_blocking(page)
                if blocking_reason == "auth_wall":
                    # Session expired -- wait for manual login
                    logger.warning(
                        "linkedin_auth_required",
                        message="Please log into LinkedIn in the browser window. "
                        f"Waiting up to {_LOGIN_WAIT_TIMEOUT}s...",
                    )
                    self._wait_for_login(page, people_url)
                    # Re-check blocking after login
                    blocking_reason = self._detect_blocking(page)

                if blocking_reason:
                    raise LinkedInBlockedError(f"LinkedIn blocked access: {blocking_reason}")

                # Extract employee cards
                people = self._extract_employee_cards(page)

                logger.info(
                    "linkedin_extraction_complete",
                    url=people_url,
                    people_found=len(people),
                )
                return people
            finally:
                context.close()

    def _detect_blocking(self, page: Any) -> str | None:
        """Detect if LinkedIn is blocking access.

        Returns blocking reason string or None if page is accessible.
        """
        try:
            page_content = page.content().lower()
        except Exception:
            return "page_error"

        # Check CAPTCHA (non-recoverable)
        for indicator in _CAPTCHA_INDICATORS:
            if indicator in page_content:
                return "captcha"

        # Check rate limit (non-recoverable)
        for indicator in _RATE_LIMIT_INDICATORS:
            if indicator in page_content:
                return "rate_limit"

        # Check auth wall (potentially recoverable via manual login)
        for indicator in _AUTH_WALL_INDICATORS:
            if indicator.lower() in page_content and (
                "authwall" in page_content
                or ("sign in" in page_content and "org-people" not in page_content)
            ):
                return "auth_wall"

        return None

    def _wait_for_login(self, page: Any, target_url: str) -> None:
        """Wait for the user to manually log in via the headed browser.

        Polls every 5 seconds up to _LOGIN_WAIT_TIMEOUT.
        """
        start = time.monotonic()
        while time.monotonic() - start < _LOGIN_WAIT_TIMEOUT:
            time.sleep(5)
            try:
                current_url = page.url
                if "linkedin.com/company" in current_url:
                    # User navigated back to the target
                    return
                # Check if auth wall is gone
                content = page.content().lower()
                if "authwall" not in content:
                    page.goto(target_url, timeout=_PAGE_TIMEOUT_MS)
                    page.wait_for_load_state("domcontentloaded", timeout=_PAGE_TIMEOUT_MS)
                    return
            except Exception:
                continue

        raise LinkedInBlockedError("Login timeout: user did not log in within time limit")

    def _extract_employee_cards(self, page: Any) -> list[dict[str, str]]:
        """Extract employee data from the People tab DOM."""
        results: list[dict[str, str]] = []

        # Try to scroll to load more cards
        try:
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 1000)")
                page.wait_for_timeout(1000)
        except Exception:
            pass  # Scroll failures are not critical

        # Try primary card selectors
        cards = page.query_selector_all(_PEOPLE_CARD_SELECTOR)

        if not cards:
            # Fallback: look for any /in/ links on the page
            return self._extract_from_links(page)

        for card in cards:
            try:
                person = self._parse_card(card)
                if person:
                    results.append(person)
            except Exception as exc:
                logger.debug("card_parse_failed", error=str(exc))
                continue

        return results

    def _parse_card(self, card: Any) -> dict[str, str] | None:
        """Parse a single employee card element."""
        # Extract name
        name_el = card.query_selector(_CARD_NAME_SELECTOR)
        name = name_el.inner_text().strip() if name_el else None

        # Extract title/subtitle
        subtitle_el = card.query_selector(_CARD_SUBTITLE_SELECTOR)
        title = subtitle_el.inner_text().strip() if subtitle_el else ""

        # Extract profile link
        link_el = card.query_selector(_CARD_LINK_SELECTOR)
        if not link_el:
            return None

        href = link_el.get_attribute("href") or ""
        profile_url = extract_linkedin_profile_url(
            f"https://www.linkedin.com{href}" if href.startswith("/") else href
        )

        if not name or not profile_url:
            return None

        return {
            "name": name,
            "title": title,
            "profile_url": profile_url,
        }

    def _extract_from_links(self, page: Any) -> list[dict[str, str]]:
        """Fallback: extract from all /in/ links on the page."""
        results: list[dict[str, str]] = []
        links = page.query_selector_all('a[href*="/in/"]')

        seen_urls: set[str] = set()
        for link in links:
            try:
                href = link.get_attribute("href") or ""
                full_url = f"https://www.linkedin.com{href}" if href.startswith("/") else href
                profile_url = extract_linkedin_profile_url(full_url)
                if not profile_url or profile_url in seen_urls:
                    continue
                seen_urls.add(profile_url)

                # Try to get text from the link or parent
                text = link.inner_text().strip()
                name = text if text else "Unknown"

                results.append(
                    {
                        "name": name,
                        "title": "",
                        "profile_url": profile_url,
                    }
                )
            except Exception:
                continue

        return results
