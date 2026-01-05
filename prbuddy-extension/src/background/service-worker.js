/**
 * PR Buddy Service Worker
 *
 * Background script for the Chrome extension.
 * Handles:
 * - WebSocket connection to backend
 * - Message routing between popup and content scripts
 * - Session management
 * - Audio and selection handling for voice/text modes
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

    case 'SELECTION_CHANGED':
      // Cache the selection so we can use it when tool requests it (without re-fetching)
      cachedSelection = message.selection;
      console.log('[SW] Cached selection:', cachedSelection?.text?.substring(0, 50));
      return { success: true };

    case 'GET_CONNECTION_STATE':
      return { success: true, state: wsManager.getState() };

    case 'SEND_AUDIO':
      return sendAudioChunk(message.audio);

    case 'SEND_SELECTION':
      return sendSelection(message.selection);

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
 * Send selection to server for voice mode.
 * Called when user starts recording with a selection active.
 * @param {Object} selection - Selection data.
 * @returns {Object} Result.
 */
function sendSelection(selection) {
  if (!selection || !selection.hasSelection) {
    return { success: true };
  }
  console.log('[SW] Sending selection for voice mode:', selection.text?.substring(0, 50));
  wsManager.send({
    type: 'selection',
    selection,
  });
  // Clear cached selection
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

// Log when service worker starts
console.log('[PR Buddy] Service worker initialized');

// Restore session on startup
chrome.storage.local.get('session').then(({ session }) => {
  if (session) {
    console.log('[SW] Found existing session:', session.session_id);
    currentSession = session;
  }
});
