/**
 * PR Buddy Service Worker
 *
 * Background script for the Chrome extension.
 * Handles:
 * - WebSocket connection to backend
 * - Message routing between popup and content scripts
 * - Session management
 * - Tool request handling (e.g., get_browser_selection)
 */

import { wsManager } from './ws-manager.js';

// Configuration
const API_BASE = 'http://localhost:8000';

// Keep track of current session
let currentSession = null;

// Cache for browser selection - captured when user selects text, used when tool requests it
let cachedSelection = null;

/**
 * Listen for messages from popup and content scripts.
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log('[SW] Received message:', message.type, 'from:', sender.tab ? 'content' : 'popup');

  handleMessage(message, sender)
    .then(response => {
      console.log('[SW] Sending response:', response);
      sendResponse(response);
    })
    .catch(error => {
      console.error('[SW] Error handling message:', error);
      sendResponse({ success: false, error: error.message });
    });

  return true; // Keep channel open for async response
});

/**
 * Handle incoming messages.
 * @param {Object} message - Message from popup or content script.
 * @param {Object} sender - Sender information.
 * @returns {Promise<Object>} Response object.
 */
async function handleMessage(message, sender) {
  switch (message.type) {
    case 'CREATE_SESSION':
      return createSession(message.prContext, message.mode, message.sessionType);

    case 'SEND_MESSAGE':
      return sendChatMessage(message.text, message.selection);

    case 'GET_SESSION':
      return getStoredSession();

    case 'END_SESSION':
      return endSession();

    case 'TOOL_RESPONSE':
      return handleToolResponse(message.requestId, message.result);

    case 'SELECTION_CHANGED':
      // Cache the selection so we can use it when tool requests it (without re-fetching)
      cachedSelection = message.selection;
      console.log('[SW] Cached selection:', cachedSelection?.text?.substring(0, 50));
      return { success: true };

    case 'GET_CONNECTION_STATE':
      return { success: true, state: wsManager.getState() };

    case 'SEND_AUDIO':
      return sendAudioChunk(message.audio);

    case 'INTERRUPT':
      return sendInterrupt();

    default:
      throw new Error(`Unknown message type: ${message.type}`);
  }
}

/**
 * Create a new session with the backend.
 * @param {Object} prContext - PR context (owner, repo, number).
 * @param {string} mode - 'text' or 'pipeline'.
 * @param {string} sessionType - 'author' or 'reviewer'.
 * @returns {Promise<Object>} Session creation result.
 */
async function createSession(prContext, mode, sessionType) {
  const prUrl = `https://github.com/${prContext.owner}/${prContext.repo}/pull/${prContext.number}`;

  console.log('[SW] Creating session:', { prUrl, mode, sessionType });

  const response = await fetch(`${API_BASE}/api/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pr_url: prUrl,
      mode: mode,
      session_type: sessionType,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to create session: ${response.status} ${error}`);
  }

  const session = await response.json();
  console.log('[SW] Session created:', session.session_id);

  // Store session info
  currentSession = {
    ...session,
    prContext,
    mode,
    sessionType,
    inputMode: mode === 'pipeline' ? 'voice' : 'text', // Track input mode
    createdAt: Date.now(),
  };

  await chrome.storage.local.set({ session: currentSession });

  // Connect WebSocket
  await wsManager.connect(session.session_id);

  // Set up event forwarding to popup
  setupEventForwarding();

  return { success: true, session: currentSession };
}

/**
 * Set up forwarding of WebSocket events to popup.
 */
function setupEventForwarding() {
  // Remove any existing listeners
  wsManager.eventListeners.clear();

  // Forward all events to popup
  wsManager.on('*', (data) => {
    console.log('[SW] Forwarding event to popup:', data.type);

    chrome.runtime.sendMessage({
      type: 'WS_EVENT',
      event: data,
    }).catch(() => {
      // Popup may not be open - that's fine
    });

    // Handle tool requests that need browser interaction
    if (data.type === 'tool_request' && data.tool === 'get_browser_selection') {
      console.log('[SW] Handling browser selection request:', data.request_id);
      handleBrowserSelectionRequest(data.request_id);
    }
  });
}

/**
 * Handle request for browser selection from backend.
 * @param {string} requestId - Tool request ID.
 */
async function handleBrowserSelectionRequest(requestId) {
  try {
    // Use cached selection if available (captured when user selected text)
    if (cachedSelection && cachedSelection.hasSelection) {
      console.log('[SW] Using cached selection:', cachedSelection.text?.substring(0, 50));
      sendToolResponse(requestId, cachedSelection);
      cachedSelection = null; // Clear after use
      return;
    }

    console.log('[SW] No cached selection, falling back to browser query');

    // Get the active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab) {
      console.log('[SW] No active tab for selection request');
      sendToolResponse(requestId, { error: 'No active tab', hasSelection: false });
      return;
    }

    // Check if the tab URL is a GitHub PR page
    if (!tab.url?.match(/github\.com\/[^/]+\/[^/]+\/pull\/\d+/)) {
      console.log('[SW] Active tab is not a GitHub PR page');
      sendToolResponse(requestId, { error: 'Not on a GitHub PR page', hasSelection: false });
      return;
    }

    console.log('[SW] Requesting selection from tab:', tab.id);

    // Helper function to request selection from content script with fast timeout
    async function requestSelection(timeoutMs = 2000) {
      return Promise.race([
        chrome.tabs.sendMessage(tab.id, {
          type: 'GET_SELECTION',
          requestId,
        }),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Content script timeout')), timeoutMs)
        ),
      ]);
    }

    // Helper function to inject and retry
    async function injectAndRetry() {
      console.log('[SW] Injecting content script...');
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['src/content/content-script.js'],
      });
      // Short wait for initialization
      await new Promise(resolve => setTimeout(resolve, 50));
      // Faster timeout after injection since script should be ready
      return requestSelection(1000);
    }

    let response;
    const startTime = Date.now();
    try {
      // First attempt with short timeout
      response = await requestSelection(1500);
      console.log('[SW] First attempt response:', response, `(${Date.now() - startTime}ms)`);

      // If undefined, content script isn't loaded - try injecting
      if (response === undefined) {
        console.log('[SW] No listener found, attempting to inject content script');
        try {
          response = await injectAndRetry();
          console.log('[SW] After injection response:', response, `(${Date.now() - startTime}ms)`);
        } catch (injectErr) {
          console.error('[SW] Injection failed:', injectErr.message);
        }
      }
    } catch (err) {
      console.log('[SW] sendMessage error:', err.message, `(${Date.now() - startTime}ms)`);
      // Try injection on error too
      try {
        response = await injectAndRetry();
        console.log('[SW] After injection response:', response, `(${Date.now() - startTime}ms)`);
      } catch (injectErr) {
        console.error('[SW] Injection also failed:', injectErr.message);
      }
    }

    console.log(`[SW] Total selection time: ${Date.now() - startTime}ms`);

    // Final check
    if (!response) {
      console.log('[SW] No response after all attempts');
      sendToolResponse(requestId, {
        error: 'Content script not responding. Please refresh the GitHub page and try again.',
        hasSelection: false,
      });
      return;
    }

    if (response.success) {
      sendToolResponse(requestId, response.result);
    } else {
      sendToolResponse(requestId, { error: response.error || 'Failed to get selection', hasSelection: false });
    }
  } catch (error) {
    console.error('[SW] Error getting selection:', error);
    sendToolResponse(requestId, { error: error.message, hasSelection: false });
  }
}

/**
 * Send tool response back to backend.
 * @param {string} requestId - Tool request ID.
 * @param {Object} result - Tool result.
 */
function sendToolResponse(requestId, result) {
  console.log('[SW] Sending tool response:', requestId, result);
  wsManager.send({
    type: 'tool_response',
    request_id: requestId,
    result,
  });
}

/**
 * Send chat message.
 * @param {string} text - Message text.
 * @param {Object} selection - Optional selection data to include.
 * @returns {Object} Result.
 */
function sendChatMessage(text, selection = null) {
  console.log('[SW] Sending chat message:', text.substring(0, 50) + '...', selection ? '(with selection)' : '');
  const payload = {
    type: 'message',
    text,
  };
  if (selection && selection.hasSelection) {
    payload.selection = selection;
  }
  wsManager.send(payload);
  // Clear cached selection after sending (it's been used)
  cachedSelection = null;
  return { success: true };
}

/**
 * Send audio chunk to backend.
 * @param {string} audio - Base64 encoded PCM16 audio.
 * @returns {Object} Result.
 */
let audioChunkCount = 0;
function sendAudioChunk(audio) {
  wsManager.send({
    type: 'audio',
    audio,
  });
  audioChunkCount++;
  // Only log occasionally to reduce noise
  if (audioChunkCount === 1 || audioChunkCount % 50 === 0) {
    console.log(`[SW] Audio chunks sent: ${audioChunkCount}`);
  }
  return { success: true };
}

/**
 * Send interrupt signal to backend.
 * @returns {Object} Result.
 */
function sendInterrupt() {
  console.log('[SW] Sending interrupt');
  wsManager.send({
    type: 'interrupt',
  });
  return { success: true };
}

/**
 * Get stored session from chrome.storage.
 * @returns {Promise<Object>} Session data.
 */
async function getStoredSession() {
  const { session } = await chrome.storage.local.get('session');

  if (session && !wsManager.isConnected()) {
    // Try to reconnect if we have a session but no connection
    try {
      await wsManager.connect(session.session_id);
      setupEventForwarding();
    } catch (error) {
      console.log('[SW] Could not reconnect to session:', error);
      // Session may be expired - clear it
      await chrome.storage.local.remove('session');
      return { success: true, session: null };
    }
  }

  currentSession = session || null;
  return { success: true, session: currentSession };
}

/**
 * End current session.
 * @returns {Promise<Object>} Result.
 */
async function endSession() {
  console.log('[SW] Ending session');

  if (currentSession) {
    wsManager.send({ type: 'end' });
  }

  wsManager.disconnect();
  currentSession = null;
  await chrome.storage.local.remove('session');

  return { success: true };
}

/**
 * Handle tool response from popup (if routed through popup).
 * @param {string} requestId - Request ID.
 * @param {Object} result - Tool result.
 * @returns {Object} Result.
 */
function handleToolResponse(requestId, result) {
  wsManager.send({
    type: 'tool_response',
    request_id: requestId,
    result,
  });
  return { success: true };
}

// Log when service worker starts
console.log('[PR Buddy] Service worker initialized');

// Restore session on startup
chrome.storage.local.get('session').then(({ session }) => {
  if (session) {
    console.log('[SW] Found existing session:', session.session_id);
    currentSession = session;
  }
});
