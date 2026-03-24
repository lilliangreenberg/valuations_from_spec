"""Prompt builders for Claude Vision analysis of LinkedIn screenshots.

Pure functions -- no I/O operations.
"""

from __future__ import annotations


def build_people_tab_prompt() -> str:
    """Build the prompt for analyzing a LinkedIn company People tab screenshot.

    The prompt asks Claude Vision to extract employee names, titles,
    and LinkedIn profile URLs visible in the screenshot.
    """
    return (
        "You are analyzing a screenshot of a LinkedIn company People tab page.\n\n"
        "Extract ALL people visible in this screenshot. For each person, provide:\n"
        "- name: The person's full name\n"
        "- title: Their job title or role description\n"
        "- profile_url: Their LinkedIn profile URL if visible (starts with "
        "linkedin.com/in/)\n\n"
        "Return the results as a JSON object with this exact structure:\n"
        '{"employees": [{"name": "...", "title": "...", "profile_url": "..."}]}\n\n'
        "Rules:\n"
        "- Include every person visible, even if partially shown\n"
        "- If a profile URL is not visible, set profile_url to null\n"
        "- If a title is not visible, set title to an empty string\n"
        "- Do not make up or guess information that is not visible\n"
        "- Return ONLY the JSON object, no other text"
    )


def build_person_profile_prompt(company_name: str) -> str:
    """Build the prompt for analyzing a personal LinkedIn profile screenshot.

    Focuses on determining if the person currently works at the specified company.

    Args:
        company_name: The company name to check employment against.
    """
    return (
        "You are analyzing a screenshot of a LinkedIn personal profile page.\n\n"
        f'Determine if this person currently works at "{company_name}".\n\n'
        "Extract the following information:\n"
        "- person_name: The person's full name\n"
        "- current_title: Their current job title (from the headline or experience)\n"
        "- current_employer: The company they currently work at\n"
        "- is_employed: true if they currently work at "
        f'"{company_name}", false otherwise\n'
        "- never_employed: true if this company does NOT appear anywhere in their "
        "experience history (meaning we may have the wrong person), false if the "
        "company appears at least once (current or past)\n"
        "- evidence: A brief explanation of how you determined the employment status\n\n"
        "Return the results as a JSON object with this exact structure:\n"
        "{"
        '"person_name": "...", '
        '"current_title": "...", '
        '"current_employer": "...", '
        '"is_employed": true/false, '
        '"never_employed": true/false, '
        '"evidence": "..."'
        "}\n\n"
        "Rules:\n"
        "- Check both the headline area and the experience section\n"
        '- A person is "currently employed" if the company appears as their current '
        'role (often marked as "Present" in dates)\n'
        "- Be flexible with company name matching (e.g., 'Acme' matches 'Acme Inc.')\n"
        "- Do not guess -- only report what is visible in the screenshot\n"
        "- Return ONLY the JSON object, no other text"
    )


def build_company_page_prompt() -> str:
    """Build the prompt for analyzing a LinkedIn company page screenshot.

    Extracts company metadata visible on the page.
    """
    return (
        "You are analyzing a screenshot of a LinkedIn company page.\n\n"
        "Extract the following information:\n"
        "- company_name: The company's name\n"
        "- industry: The industry or sector\n"
        "- tagline: The company tagline or description\n"
        "- employee_count: Number of employees if visible\n"
        "- follower_count: Number of followers if visible\n"
        "- any_leadership_visible: Names and titles of any leadership/executives "
        "visible on the page\n\n"
        "Return the results as a JSON object with this exact structure:\n"
        "{"
        '"company_name": "...", '
        '"industry": "...", '
        '"tagline": "...", '
        '"employee_count": "...", '
        '"follower_count": "...", '
        '"leadership": [{"name": "...", "title": "..."}]'
        "}\n\n"
        "Rules:\n"
        "- If a field is not visible, set it to null\n"
        "- Do not guess or make up information\n"
        "- Return ONLY the JSON object, no other text"
    )
