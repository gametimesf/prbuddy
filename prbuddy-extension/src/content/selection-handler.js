/**
 * Text selection handling for GitHub PR pages.
 */

/**
 * Get the currently selected text and surrounding context.
 * @returns {Object} Selection data with text and context.
 */
export function getSelection() {
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

  // Get context about where the selection is
  const context = getSelectionContext(selection);

  return {
    text,
    hasSelection: true,
    context,
  };
}

/**
 * Extract context about where the selection is (file, line numbers, etc.)
 * @param {Selection} selection - Browser selection object.
 * @returns {Object} Context information.
 */
function getSelectionContext(selection) {
  const range = selection.getRangeAt(0);
  const container = range.commonAncestorContainer;
  const element = container.nodeType === Node.TEXT_NODE
    ? container.parentElement
    : container;

  // Check if selection is within a diff file
  const diffFile = element.closest?.('.file') ||
                   element.closest?.('[data-file-type]');

  if (diffFile) {
    // Get file path from diff header
    const filePath = diffFile.querySelector('[data-path]')?.getAttribute('data-path') ||
                     diffFile.querySelector('.file-header')?.getAttribute('data-path') ||
                     diffFile.querySelector('.file-info a')?.textContent?.trim() ||
                     diffFile.querySelector('.Truncate a')?.textContent?.trim();

    // Try to get line numbers
    const lineEl = element.closest?.('tr') || element.closest?.('.blob-code');
    const lineNumber = lineEl?.querySelector('[data-line-number]')?.getAttribute('data-line-number') ||
                       lineEl?.getAttribute('data-line-number');

    // Determine if it's an addition, deletion, or context line
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

  // Check if in a code block (in comments or description)
  const codeBlock = element.closest?.('pre') || element.closest?.('.highlight');
  if (codeBlock) {
    // Try to determine language from class
    const langClass = codeBlock.className.match(/highlight-source-(\w+)|language-(\w+)/);
    const language = langClass ? (langClass[1] || langClass[2]) : null;

    return {
      type: 'code_block',
      language,
    };
  }

  // Check if in conversation/comment
  const comment = element.closest?.('.comment-body') ||
                  element.closest?.('.review-comment');
  if (comment) {
    // Try to get the comment author
    const commentContainer = comment.closest?.('.timeline-comment') ||
                            comment.closest?.('.review-comment');
    const commentAuthor = commentContainer?.querySelector('.author')?.textContent?.trim();

    return {
      type: 'comment',
      author: commentAuthor || null,
    };
  }

  // Check if in PR description
  const description = element.closest?.('.comment-body.markdown-body');
  if (description && description.closest?.('.js-comment-container')?.classList?.contains('timeline-comment--caret')) {
    return {
      type: 'description',
    };
  }

  // Check if in PR title
  if (element.closest?.('.js-issue-title') || element.closest?.('.gh-header-title')) {
    return {
      type: 'title',
    };
  }

  return {
    type: 'unknown',
  };
}

/**
 * Set up a listener for selection changes.
 * @param {Function} callback - Called when selection changes.
 * @returns {Function} Cleanup function to remove listener.
 */
export function onSelectionChange(callback) {
  let debounceTimeout = null;

  const handler = () => {
    // Debounce to avoid too many callbacks
    clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(() => {
      const selection = getSelection();
      callback(selection);
    }, 150);
  };

  document.addEventListener('selectionchange', handler);

  // Return cleanup function
  return () => {
    document.removeEventListener('selectionchange', handler);
    clearTimeout(debounceTimeout);
  };
}
