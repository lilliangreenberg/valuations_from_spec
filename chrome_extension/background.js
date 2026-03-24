/**
 * LinkedIn Profile Scraper - Background Service Worker
 *
 * Coordinates screenshot capture and message routing between
 * CDP (Chrome DevTools Protocol) and the content script.
 */

function handleMessage(message, sender, sendResponse) {
  if (message.action === "captureScreenshot") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs || tabs.length === 0) {
        sendResponse({ success: false, error: "No active tab found" });
        return;
      }
      chrome.tabs.captureVisibleTab(null, { format: "png" }, (dataUrl) => {
        if (chrome.runtime.lastError) {
          sendResponse({
            success: false,
            error: chrome.runtime.lastError.message,
          });
        } else {
          sendResponse({ success: true, dataUrl: dataUrl });
        }
      });
    });
    return true;
  }

  if (message.action === "extractFromTab") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs || tabs.length === 0) {
        sendResponse({ success: false, error: "No active tab found" });
        return;
      }
      chrome.tabs.sendMessage(
        tabs[0].id,
        { action: "extractProfile" },
        (response) => {
          if (chrome.runtime.lastError) {
            sendResponse({
              success: false,
              error: chrome.runtime.lastError.message,
            });
          } else {
            sendResponse(response);
          }
        }
      );
    });
    return true;
  }

  return false;
}

chrome.runtime.onMessageExternal.addListener(handleMessage);
chrome.runtime.onMessage.addListener(handleMessage);
