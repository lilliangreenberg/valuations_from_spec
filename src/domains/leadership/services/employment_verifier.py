"""Employment verification service for LinkedIn leadership profiles.

Verifies whether known leaders are still employed at their company
by visiting their personal LinkedIn profiles and analyzing the results.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.domains.leadership.core.employment_check import (
    STATUS_DEPARTED,
    STATUS_WRONG_PERSON,
    determine_employment_status,
)
from src.domains.leadership.core.vision_prompts import build_person_profile_prompt
from src.domains.leadership.core.vision_result_parser import (
    parse_person_employment_result,
)
from src.domains.leadership.services.cdp_browser import CDPBlockedError

if TYPE_CHECKING:
    from src.domains.leadership.repositories.leadership_repository import (
        LeadershipRepository,
    )
    from src.domains.leadership.repositories.linkedin_snapshot_repository import (
        LinkedInSnapshotRepository,
    )
    from src.domains.leadership.services.cdp_browser import CDPBrowser
    from src.services.llm_client import LLMClient

logger = structlog.get_logger(__name__)


class EmploymentVerifier:
    """Verifies employment status of known leaders via LinkedIn profile visits."""

    def __init__(
        self,
        cdp_browser: CDPBrowser,
        llm_client: LLMClient,
        leadership_repo: LeadershipRepository,
        snapshot_repo: LinkedInSnapshotRepository,
    ) -> None:
        self.browser = cdp_browser
        self.llm = llm_client
        self.leadership_repo = leadership_repo
        self.snapshot_repo = snapshot_repo

    def verify_leader(
        self,
        company_id: int,
        company_name: str,
        leader_record: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify a single leader's employment status.

        Args:
            company_id: The company ID.
            company_name: The company name for matching.
            leader_record: Dict with person_name, title, linkedin_profile_url.

        Returns:
            Dict with: status, confidence, evidence, person_name, title,
            profile_url, change_detected
        """
        person_name = leader_record.get("person_name", "Unknown")
        profile_url = leader_record.get("linkedin_profile_url", "")
        title = leader_record.get("title", "")
        now = datetime.now(UTC).isoformat()

        logger.info(
            "employment_verification_start",
            person=person_name,
            company=company_name,
            url=profile_url,
        )

        # Navigate to personal profile and extract data
        dom_data: dict[str, Any] = {}
        vision_data: dict[str, Any] = {}
        page_html = ""
        screenshot_path = ""

        try:
            dom_data = self.browser.extract_person_profile(profile_url)
            page_html = self.browser.get_page_html()

            # Capture screenshot and analyze with Vision
            screenshot_bytes = self.browser.capture_screenshot()
            screenshot_path = self.browser.capture_profile_screenshot(
                company_id, person_name
            )

            # Send to Claude Vision
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            prompt = build_person_profile_prompt(company_name)
            raw_vision = self.llm.analyze_screenshot(screenshot_b64, prompt)

            if not raw_vision.get("error"):
                vision_data = parse_person_employment_result(raw_vision)
            else:
                logger.warning(
                    "employment_vision_analysis_failed",
                    person=person_name,
                    error=raw_vision.get("error"),
                )

        except CDPBlockedError as exc:
            logger.error(
                "employment_verification_blocked",
                person=person_name,
                url=profile_url,
                error=str(exc),
            )
            return {
                "status": "error",
                "confidence": 0.0,
                "evidence": f"LinkedIn blocked access: {exc}",
                "person_name": person_name,
                "title": title,
                "profile_url": profile_url,
                "change_detected": False,
            }
        except Exception as exc:
            logger.error(
                "employment_verification_failed",
                person=person_name,
                url=profile_url,
                error=str(exc),
                exc_info=True,
            )
            return {
                "status": "error",
                "confidence": 0.0,
                "evidence": f"Verification failed: {exc}",
                "person_name": person_name,
                "title": title,
                "profile_url": profile_url,
                "change_detected": False,
            }

        # Determine employment status
        result = determine_employment_status(dom_data, vision_data, company_name)
        status = result["status"]
        change_detected = status in (STATUS_DEPARTED, STATUS_WRONG_PERSON)

        # Store LinkedIn snapshot
        self.snapshot_repo.store_snapshot({
            "company_id": company_id,
            "linkedin_url": profile_url,
            "url_type": "person",
            "person_name": person_name,
            "content_html": page_html,
            "content_json": json.dumps(dom_data),
            "vision_data_json": json.dumps(vision_data),
            "screenshot_path": screenshot_path,
            "captured_at": now,
        })

        # Update leadership record based on result
        if status == STATUS_DEPARTED:
            self.leadership_repo.mark_not_current(company_id, profile_url)
            logger.warning(
                "leader_departed_detected",
                person=person_name,
                title=title,
                company=company_name,
                evidence=result["evidence"],
            )
        elif status == STATUS_WRONG_PERSON:
            self.leadership_repo.mark_not_current(company_id, profile_url)
            logger.warning(
                "wrong_person_detected",
                person=person_name,
                title=title,
                company=company_name,
                evidence=result["evidence"],
                confidence=result["confidence"],
            )
        else:
            # Still employed or unknown -- update verification date
            self.leadership_repo.update_verification_date(
                company_id, profile_url, now
            )

        logger.info(
            "employment_verification_complete",
            person=person_name,
            company=company_name,
            status=status,
            confidence=result["confidence"],
            change_detected=change_detected,
        )

        return {
            "status": status,
            "confidence": result["confidence"],
            "evidence": result["evidence"],
            "person_name": person_name,
            "title": title,
            "profile_url": profile_url,
            "change_detected": change_detected,
            "current_title": result.get("current_title", ""),
            "current_employer": result.get("current_employer", ""),
        }

    def verify_all_leaders(
        self,
        company_id: int,
        company_name: str,
    ) -> list[dict[str, Any]]:
        """Verify all current leaders for a company.

        Returns list of verification results.
        """
        leaders = self.leadership_repo.get_current_leadership(company_id)
        results: list[dict[str, Any]] = []

        for leader in leaders:
            result = self.verify_leader(company_id, company_name, leader)
            results.append(result)
            # Delay between profiles to avoid rate limiting
            self.browser.delay_between_pages()

        return results
