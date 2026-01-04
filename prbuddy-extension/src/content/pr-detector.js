/**
 * PR context detection for GitHub pages.
 */

/**
 * Detect PR context from the current GitHub page.
 *
 * URL pattern: https://github.com/{owner}/{repo}/pull/{number}
 * Also extracts metadata from page elements when available.
 *
 * @returns {Object|null} PR context or null if not on a PR page.
 */
export function detectPRContext() {
  const url = window.location.href;
  const match = url.match(/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/);

  if (!match) {
    return null;
  }

  const [, owner, repo, number] = match;

  // Try to get additional context from page elements
  const prTitle = document.querySelector('.js-issue-title')?.textContent?.trim() ||
                  document.querySelector('[data-hovercard-type="pull_request"]')?.textContent?.trim();
  const prAuthor = document.querySelector('.author')?.textContent?.trim() ||
                   document.querySelector('.pull-header-username')?.textContent?.trim();
  const prState = document.querySelector('.State')?.textContent?.trim()?.toLowerCase();

  // Try to get branch info
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
 * @returns {boolean}
 */
export function isOnPRPage() {
  return /github\.com\/[^/]+\/[^/]+\/pull\/\d+/.test(window.location.href);
}

/**
 * Get the current tab within the PR (conversation, commits, files changed, etc.)
 * @returns {string} Tab name or 'conversation' as default.
 */
export function getCurrentPRTab() {
  const url = window.location.href;

  if (url.includes('/files')) return 'files';
  if (url.includes('/commits')) return 'commits';
  if (url.includes('/checks')) return 'checks';

  return 'conversation';
}
