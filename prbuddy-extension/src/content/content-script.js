/**
 * PR Buddy Content Script
 *
 * Runs on GitHub PR pages to:
 * - Detect PR context (owner, repo, number)
 * - Capture text selections for the "What is this?" feature
 * - Respond to requests from popup/service worker
 */

// Import utilities (note: content scripts can't use ES modules directly in MV3,
// so we'll inline the functionality here)

/**
 * Detect PR context from the current GitHub page.
 */
function detectPRContext() {
  const url = window.location.href;
  const match = url.match(/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/);

  if (!match) {
    return null;
  }

  const [, owner, repo, number] = match;

  // Get additional context from page elements
  const prTitle = document.querySelector('.js-issue-title')?.textContent?.trim() ||
                  document.querySelector('[data-hovercard-type="pull_request"]')?.textContent?.trim();
  const prAuthor = document.querySelector('.author')?.textContent?.trim();
  const prState = document.querySelector('.State')?.textContent?.trim()?.toLowerCase();
  const baseBranch = document.querySelector('.base-ref')?.textContent?.trim();
  const headBranch = document.querySelector('.head-ref')?.textContent?.trim();

  return {
    owner,
    repo,
    number: parseInt(number, 10),
    url,
    title: prTitle || null,
    author: prAuthor || null,
    state: prState || null,
    baseBranch: baseBranch || null,
    headBranch: headBranch || null,
  };
}

/**
 * Check if current page is a GitHub PR page.
 */
function isOnPRPage() {
  return /github\.com\/[^/]+\/[^/]+\/pull\/\d+/.test(window.location.href);
}

/**
 * Get the currently selected text and context.
 * NOTE: Named getBrowserSelection to avoid conflict with window.getSelection()
 */
function getBrowserSelection() {
  const selection = window.getSelection();

  if (!selection || selection.isCollapsed) {
    return {
      text: '',
      hasSelection: false,
      context: null,
    };
  }

  const text = selection.toString().trim();

  if (!text) {
    return {
      text: '',
      hasSelection: false,
      context: null,
    };
  }

  const context = getSelectionContext(selection);

  return {
    text,
    hasSelection: true,
    context,
  };
}

/**
 * Extract context about where the selection is.
 */
function getSelectionContext(selection) {
  const range = selection.getRangeAt(0);
  const container = range.commonAncestorContainer;
  const element = container.nodeType === Node.TEXT_NODE
    ? container.parentElement
    : container;

  // Check if in diff file
  const diffFile = element.closest?.('.file') || element.closest?.('[data-file-type]');

  if (diffFile) {
    const filePath = diffFile.querySelector('[data-path]')?.getAttribute('data-path') ||
                     diffFile.querySelector('.file-header')?.getAttribute('data-path') ||
                     diffFile.querySelector('.file-info a')?.textContent?.trim() ||
                     diffFile.querySelector('.Truncate a')?.textContent?.trim();

    const lineEl = element.closest?.('tr') || element.closest?.('.blob-code');
    const lineNumber = lineEl?.querySelector('[data-line-number]')?.getAttribute('data-line-number') ||
                       lineEl?.getAttribute('data-line-number');

    let changeType = 'context';
    if (lineEl?.classList?.contains('blob-code-addition') || lineEl?.classList?.contains('addition')) {
      changeType = 'addition';
    } else if (lineEl?.classList?.contains('blob-code-deletion') || lineEl?.classList?.contains('deletion')) {
      changeType = 'deletion';
    }

    return {
      type: 'diff',
      filePath: filePath || null,
      lineNumber: lineNumber ? parseInt(lineNumber, 10) : null,
      changeType,
    };
  }

  // Check if in code block
  const codeBlock = element.closest?.('pre') || element.closest?.('.highlight');
  if (codeBlock) {
    const langClass = codeBlock.className.match(/highlight-source-(\w+)|language-(\w+)/);
    const language = langClass ? (langClass[1] || langClass[2]) : null;
    return { type: 'code_block', language };
  }

  // Check if in comment
  const comment = element.closest?.('.comment-body') || element.closest?.('.review-comment');
  if (comment) {
    const commentContainer = comment.closest?.('.timeline-comment') || comment.closest?.('.review-comment');
    const commentAuthor = commentContainer?.querySelector('.author')?.textContent?.trim();
    return { type: 'comment', author: commentAuthor || null };
  }

  // Check if in PR description
  const description = element.closest?.('.comment-body.markdown-body');
  if (description) {
    return { type: 'description' };
  }

  // Check if in PR title
  if (element.closest?.('.js-issue-title') || element.closest?.('.gh-header-title')) {
    return { type: 'title' };
  }

  return { type: 'unknown' };
}

/**
 * Handle messages from popup or service worker.
 */
function handleMessage(message, sender, sendResponse) {
  console.log('[PR Buddy] Content script received:', message.type, 'at', window.location.href);

  try {
    switch (message.type) {
      case 'GET_PR_CONTEXT':
        const context = detectPRContext();
        console.log('[PR Buddy] Sending PR context:', context);
        sendResponse({ success: !!context, context });
        return false; // Synchronous response

      case 'GET_SELECTION':
        const selection = getBrowserSelection();
        console.log('[PR Buddy] Sending selection:', selection);
        sendResponse({
          success: true,
          requestId: message.requestId,
          result: selection,
        });
        return false; // Synchronous response

      case 'PING':
        console.log('[PR Buddy] Ping received, sending pong');
        sendResponse({ success: true, message: 'pong' });
        return false; // Synchronous response

      default:
        console.log('[PR Buddy] Unknown message type:', message.type);
        sendResponse({ success: false, error: 'Unknown message type' });
        return false;
    }
  } catch (error) {
    console.error('[PR Buddy] Error handling message:', error);
    sendResponse({ success: false, error: error.message });
    return false;
  }
}

/**
 * Initialize content script.
 */
function init() {
  const onPRPage = isOnPRPage();
  console.log('[PR Buddy] Content script initializing, onPRPage:', onPRPage, 'URL:', window.location.href);

  // ALWAYS register the message listener - even if not on a PR page
  // This ensures injected scripts can respond to messages
  chrome.runtime.onMessage.addListener(handleMessage);
  console.log('[PR Buddy] Message listener registered');

  if (!onPRPage) {
    console.log('[PR Buddy] Not a PR page, skipping selection tracking');
    return;
  }

  console.log('[PR Buddy] Content script fully initialized on PR page');

  // Track selection changes for UI feedback
  let lastSelectionText = '';
  document.addEventListener('selectionchange', () => {
    const selection = getBrowserSelection();
    const newText = selection.text || '';

    // Only notify if selection actually changed
    if (newText !== lastSelectionText) {
      lastSelectionText = newText;
      // Notify extension about selection change (including when cleared)
      chrome.runtime.sendMessage({
        type: 'SELECTION_CHANGED',
        selection,
      }).catch(() => {
        // Popup may not be open - that's fine
      });
    }
  });
}

// Prevent duplicate initialization if script is injected multiple times
if (window.__prBuddyContentScriptLoaded) {
  console.log('[PR Buddy] Content script already loaded, skipping');
} else {
  window.__prBuddyContentScriptLoaded = true;
  console.log('[PR Buddy] Content script loading...');
  init();
}
