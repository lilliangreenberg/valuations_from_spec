/**
 * LinkedIn Profile Scraper - Content Script
 *
 * Extracts profile/company data directly from the LinkedIn page DOM.
 * Communicates with the background script via chrome.runtime messages.
 *
 * Supports three extraction modes:
 *   - extractProfile: Personal profile data (name, headline, experience, etc.)
 *   - extractCompanyPeople: Company People tab employee cards
 *   - closePopups: Dismiss LinkedIn overlay modals
 */

// --- Personal Profile Extraction ---

function extractProfileData() {
  var data = {};

  // Name
  var nameEl =
    document.querySelector("h1.text-heading-xlarge") ||
    document.querySelector("h1.inline.t-24") ||
    document.querySelector(".pv-top-card--list h1") ||
    document.querySelector("h1");
  if (nameEl) {
    data.name = nameEl.innerText.trim();
  }

  // Headline
  var headlineEl =
    document.querySelector("div.text-body-medium.break-words") ||
    document.querySelector(".pv-top-card--list .text-body-medium") ||
    document.querySelector(".ph5 .mt2 .text-body-medium");
  if (headlineEl) {
    data.headline = headlineEl.innerText.trim();
  }

  // Location
  var locationEl =
    document.querySelector(
      "span.text-body-small.inline.t-black--light.break-words"
    ) ||
    document.querySelector(".pv-top-card--list-bullet .text-body-small");
  if (locationEl) {
    data.location = locationEl.innerText.trim();
  }

  // About / Summary
  var aboutSection =
    document.querySelector("#about ~ div .inline-show-more-text") ||
    document.querySelector("#about + .display-flex .inline-show-more-text") ||
    document.querySelector(
      "section.pv-about-section .pv-about__summary-text"
    );
  if (aboutSection) {
    data.about = aboutSection.innerText.trim();
  }

  // Connection / follower count
  var connectionsEl =
    document.querySelector("span.t-bold:not(.text-heading-xlarge)") ||
    document.querySelector(".pv-top-card--list-bullet li:last-child span");
  if (connectionsEl) {
    var text = connectionsEl.innerText.trim();
    if (
      /\d/.test(text) &&
      (text.includes("connection") ||
        text.includes("follower") ||
        /^\d/.test(text))
    ) {
      data.connections = text;
    }
  }

  // Profile photo URL
  var profileImg =
    document.querySelector("img.pv-top-card-profile-picture__image--show") ||
    document.querySelector("img.pv-top-card-profile-picture__image") ||
    document.querySelector(".pv-top-card--photo-resize img") ||
    document.querySelector("img.presence-entity__image");
  if (profileImg) {
    var src = profileImg.getAttribute("src");
    if (src && src.startsWith("http")) {
      data.profile_image_url = src;
    }
  }

  // Experience entries
  var experienceSection = document.getElementById("experience");
  if (experienceSection) {
    var container = experienceSection.closest("section");
    if (container) {
      var entries = container.querySelectorAll("li.artdeco-list__item");
      var experience = [];
      entries.forEach(function (entry) {
        var titleEl =
          entry.querySelector("span.mr1.t-bold span") ||
          entry.querySelector("span.t-bold span") ||
          entry.querySelector(".t-bold");
        var companyEl =
          entry.querySelector("span.t-14.t-normal span") ||
          entry.querySelector(".t-14.t-normal");
        var datesEl =
          entry.querySelector("span.t-14.t-normal.t-black--light span") ||
          entry.querySelector(".t-black--light span");
        var companyLink = entry.querySelector('a[href*="/company/"]');

        var exp = {};
        if (titleEl) exp.title = titleEl.innerText.trim();
        if (companyEl) exp.company = companyEl.innerText.trim();
        if (datesEl) exp.dates = datesEl.innerText.trim();
        if (companyLink) {
          exp.company_linkedin_url = companyLink.href
            .split("?")[0]
            .replace(/\/+$/, "");
        }
        if (Object.keys(exp).length > 0) {
          experience.push(exp);
        }
      });
      if (experience.length > 0) {
        data.experience = experience;
      }
    }
  }

  // Current page URL
  data.profile_url = window.location.href;

  return data;
}

// --- Company People Tab Extraction ---

function extractCompanyPeopleData() {
  var data = { employees: [] };
  var seen = {};

  // Primary card selectors
  var cardSelectors = [
    'div[class*="org-people-profile-card"]',
    'li[class*="org-people-profiles-module__profile-card"]',
    'div[data-test-id="org-people-profile-card"]',
  ];

  var cards = [];
  for (var i = 0; i < cardSelectors.length; i++) {
    var found = document.querySelectorAll(cardSelectors[i]);
    if (found.length > 0) {
      cards = found;
      break;
    }
  }

  if (cards.length > 0) {
    cards.forEach(function (card) {
      try {
        var nameEl =
          card.querySelector('[class*="profile-card__title"]') ||
          card.querySelector(
            '[class*="org-people-profile-card__profile-title"]'
          ) ||
          card.querySelector('[class*="artdeco-entity-lockup__title"]');

        var subtitleEl =
          card.querySelector('[class*="profile-card__subtitle"]') ||
          card.querySelector('[class*="org-people-profile-card__subtitle"]') ||
          card.querySelector('[class*="artdeco-entity-lockup__subtitle"]');

        var linkEl = card.querySelector('a[href*="/in/"]');

        var name = nameEl ? nameEl.innerText.trim() : null;
        var title = subtitleEl ? subtitleEl.innerText.trim() : "";
        var profileUrl = null;

        if (linkEl) {
          var href = linkEl.getAttribute("href") || "";
          profileUrl = href.startsWith("/")
            ? "https://www.linkedin.com" + href.split("?")[0]
            : href.split("?")[0];
        }

        if (name && profileUrl && !seen[profileUrl]) {
          seen[profileUrl] = true;
          data.employees.push({
            name: name,
            title: title,
            profile_url: profileUrl,
          });
        }
      } catch (e) {
        // Skip broken cards
      }
    });
  }

  // Fallback: extract all /in/ links on the page
  if (data.employees.length === 0) {
    var links = document.querySelectorAll('a[href*="/in/"]');
    links.forEach(function (link) {
      try {
        var href = link.getAttribute("href") || "";
        var fullUrl = href.startsWith("/")
          ? "https://www.linkedin.com" + href.split("?")[0]
          : href.split("?")[0];
        if (fullUrl && !seen[fullUrl]) {
          seen[fullUrl] = true;
          var linkText = link.innerText.trim();
          data.employees.push({
            name: linkText || "Unknown",
            title: "",
            profile_url: fullUrl,
          });
        }
      } catch (e) {
        // Skip broken links
      }
    });
  }

  // Company page metadata
  var companyNameEl =
    document.querySelector("h1.org-top-card-summary__title span") ||
    document.querySelector("h1.org-top-card-summary__title");
  if (companyNameEl) {
    data.company_name = companyNameEl.innerText.trim();
  }

  data.page_url = window.location.href;
  data.employee_count = data.employees.length;

  return data;
}

// --- Popup Dismissal ---

function closePopups() {
  var selectors = [
    'button[aria-label="Dismiss"]',
    'button[aria-label="Close"]',
    "button.msg-overlay-bubble-header__control--close",
    'button[action-type="DENY"]',
    ".artdeco-modal__dismiss",
    ".artdeco-toast-item__dismiss",
    "#artdeco-global-alert-container button",
  ];
  var closed = 0;
  selectors.forEach(function (sel) {
    try {
      document.querySelectorAll(sel).forEach(function (btn) {
        if (btn.offsetParent !== null) {
          btn.click();
          closed++;
        }
      });
    } catch (e) {
      // ignore
    }
  });
  return closed;
}

// --- Message Listener ---

chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  if (message.action === "extractProfile") {
    closePopups();
    var profileData = extractProfileData();
    sendResponse({ success: true, data: profileData });
  } else if (message.action === "extractCompanyPeople") {
    closePopups();
    var peopleData = extractCompanyPeopleData();
    sendResponse({ success: true, data: peopleData });
  } else if (message.action === "closePopups") {
    var closedCount = closePopups();
    sendResponse({ success: true, closed: closedCount });
  }
  return true;
});
