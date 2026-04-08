/**
 * PR Buddy Extension Side Panel
 *
 * Persistent sidebar UI for the Chrome extension.
 * Handles mode selection, chat interface, and message display.
 *
 * Key differences from popup:
 * - Stays open while browsing the PR page
 * - Listens for tab changes to update PR context
 * - Handles mic permission workaround for side panels
 */

// State
let currentSession = null;
let prContext = null;
let currentSelection = null;
let selectedInputMode = 'text'; // 'text' or 'voice'

// Audio state
let isRecording = false;
let isPlaying = false;
let speechRecognition = null;
let playbackContext = null;
let masterGain = null;
let audioQueue = [];
let scheduledEndTime = 0;
let scheduledCount = 0;
let activeAudioSources = [];
let audioStreamEnded = false;

// Audio config (set by server)
let outputSampleRate = 16000;
const MIN_BUFFER_CHUNKS = 2;
const MAX_SCHEDULED_AHEAD = 2;

// DOM elements
const loadingEl = document.getElementById('loading');
const notPrPageEl = document.getElementById('not-pr-page');
const connectionErrorEl = document.getElementById('connection-error');
const micPermissionEl = document.getElementById('mic-permission');
const modeSelectionEl = document.getElementById('mode-selection');
const chatInterfaceEl = document.getElementById('chat-interface');
const chatMessagesEl = document.getElementById('chatMessages');
const messageInputEl = document.getElementById('messageInput');
const sendBtnEl = document.getElementById('sendBtn');
const endSessionBtnEl = document.getElementById('endSessionBtn');
const selectionHintEl = document.getElementById('selectionHint');
const selectionTextEl = document.getElementById('selectionText');
const clearSelectionEl = document.getElementById('clearSelection');
const toolActivityEl = document.getElementById('toolActivity');
const toolNameEl = document.getElementById('toolName');
const connectionStatusEl = document.getElementById('connectionStatus');
const errorMessageEl = document.getElementById('errorMessage');
const retryBtnEl = document.getElementById('retryBtn');
const micBtnEl = document.getElementById('micBtn');
const listeningIndicatorEl = document.getElementById('listeningIndicator');
const requestMicBtnEl = document.getElementById('requestMicBtn');
const skipMicBtnEl = document.getElementById('skipMicBtn');
const flowModeIndicatorEl = document.getElementById('flowModeIndicator');
const flowModeBtnEl = document.getElementById('flowModeBtn');
const flowEngageBtnEl = document.getElementById('flowEngageBtn');

// Flow mode state
let isFlowMode = false;

/**
 * Initialize side panel.
 */
async function init() {
  console.log('[SidePanel] Initializing...');

  // Register message listener early so we can receive selection changes
  chrome.runtime.onMessage.addListener(handleRuntimeMessage);

  // Listen for mic permission changes (fallback if runtime message doesn't arrive)
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== 'local') return;
    const micPermEl = document.getElementById('mic-permission');
    if (!micPermEl || micPermEl.style.display === 'none') return;

    if (changes.micPermissionGranted?.newValue === true) {
      console.log('[SidePanel] Mic permission detected via storage change');
      selectedInputMode = 'voice';
      showModeSelection();
    } else if (changes.micPermissionSkipped?.newValue === true) {
      console.log('[SidePanel] Mic skip detected via storage change');
      selectedInputMode = 'text';
      showModeSelection();
    }
  });

  // Check for existing session first
  try {
    const sessionResponse = await chrome.runtime.sendMessage({ type: 'GET_SESSION' });
    console.log('[SidePanel] Session response:', sessionResponse);

    if (sessionResponse.success && sessionResponse.session) {
      currentSession = sessionResponse.session;
      prContext = currentSession.prContext;
      showChatInterface();
      return;
    }
  } catch (error) {
    console.error('[SidePanel] Error getting session:', error);
  }

  // No existing session - check if we're on a PR page
  await detectPRContext();
}

/**
 * Detect PR context from current tab.
 */
async function detectPRContext() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab) {
      console.log('[SidePanel] No active tab');
      showNotPrPage();
      return;
    }

    console.log('[SidePanel] Active tab:', tab.url);

    // Check if URL looks like a GitHub PR
    if (!tab.url?.match(/github\.com\/[^/]+\/[^/]+\/pull\/\d+/)) {
      showNotPrPage();
      return;
    }

    // Try to get context from content script
    try {
      const response = await chrome.tabs.sendMessage(tab.id, { type: 'GET_PR_CONTEXT' });
      console.log('[SidePanel] PR context response:', response);

      if (response.success && response.context) {
        prContext = response.context;
        showModeSelection();
      } else {
        showNotPrPage();
      }
    } catch (error) {
      console.log('[SidePanel] Content script not ready, parsing URL directly');

      // Parse URL directly as fallback
      const match = tab.url.match(/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/);
      if (match) {
        prContext = {
          owner: match[1],
          repo: match[2],
          number: parseInt(match[3], 10),
          url: tab.url,
        };
        showModeSelection();
      } else {
        showNotPrPage();
      }
    }
  } catch (error) {
    console.error('[SidePanel] Error detecting PR context:', error);
    showNotPrPage();
  }
}

// ============================================
// Tab Change Listeners (Side Panel Specific)
// ============================================

/**
 * Listen for tab URL changes to update PR context.
 * Important because side panel stays open across navigation.
 */
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete') return;

  // Get the active tab in the current window
  const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });

  if (activeTab?.id !== tabId) return; // Not our tab

  // Check if we navigated to a different PR
  const isPRPage = tab.url?.match(/github\.com\/[^/]+\/[^/]+\/pull\/\d+/);

  if (isPRPage) {
    const match = tab.url.match(/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/);
    if (match) {
      const newPrContext = {
        owner: match[1],
        repo: match[2],
        number: parseInt(match[3], 10),
        url: tab.url,
      };

      // Check if PR changed
      if (!prContext ||
          prContext.owner !== newPrContext.owner ||
          prContext.repo !== newPrContext.repo ||
          prContext.number !== newPrContext.number) {
        console.log('[SidePanel] PR context changed:', newPrContext);

        // End existing session if PR changed
        if (currentSession) {
          await endSession();
        }

        prContext = newPrContext;
        showModeSelection();
      }
    }
  } else if (!isPRPage && !currentSession) {
    // Navigated away from PR page without a session
    showNotPrPage();
  }
});

/**
 * Listen for tab activation to refresh context.
 */
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId);

  const isPRPage = tab.url?.match(/github\.com\/[^/]+\/[^/]+\/pull\/\d+/);

  if (isPRPage && !currentSession) {
    // Switched to a PR tab without a session - detect context
    await detectPRContext();
  } else if (!isPRPage && !currentSession) {
    showNotPrPage();
  }
});

// ============================================
// UI State Management
// ============================================

/**
 * Hide all state panels.
 */
function hideAll() {
  loadingEl.style.display = 'none';
  notPrPageEl.style.display = 'none';
  connectionErrorEl.style.display = 'none';
  micPermissionEl.style.display = 'none';
  modeSelectionEl.style.display = 'none';
  chatInterfaceEl.style.display = 'none';
}

/**
 * Show loading state.
 */
function showLoading(message = 'Loading...') {
  hideAll();
  loadingEl.style.display = 'flex';
  loadingEl.querySelector('p').textContent = message;
}

/**
 * Show not on PR page state.
 */
function showNotPrPage() {
  hideAll();
  notPrPageEl.style.display = 'flex';
}

/**
 * Show connection error state.
 */
function showConnectionError(message) {
  hideAll();
  connectionErrorEl.style.display = 'flex';
  errorMessageEl.textContent = message;
}

/**
 * Show mic permission request panel.
 */
function showMicPermission() {
  hideAll();
  micPermissionEl.style.display = 'flex';
}

/**
 * Show mode selection screen.
 */
function showModeSelection() {
  hideAll();
  modeSelectionEl.style.display = 'flex';

  document.getElementById('prBadge').textContent =
    `${prContext.owner}/${prContext.repo}#${prContext.number}`;

  if (prContext.title) {
    document.getElementById('prTitle').textContent = prContext.title;
  }

  // Set up input mode toggle handlers
  const textModeBtn = document.getElementById('textModeBtn');
  const voiceModeBtn = document.getElementById('voiceModeBtn');

  textModeBtn.onclick = () => {
    selectedInputMode = 'text';
    textModeBtn.classList.add('active');
    voiceModeBtn.classList.remove('active');
  };

  voiceModeBtn.onclick = async () => {
    // Check mic permission before allowing voice mode selection
    const hasPermission = await checkMicPermission();
    if (hasPermission) {
      selectedInputMode = 'voice';
      voiceModeBtn.classList.add('active');
      textModeBtn.classList.remove('active');
    } else {
      // Show mic permission request
      showMicPermission();
    }
  };

  // Set up mode button handlers
  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.onclick = () => {
      const sessionType = btn.dataset.mode;
      createSession(sessionType);
    };
  });
}

// ============================================
// Microphone Permission Handling
// ============================================

/**
 * Check if microphone permission is granted.
 * Side panels can't request mic permission directly - need workaround.
 */
async function checkMicPermission() {
  try {
    // Check stored permission state first
    const { micPermissionGranted, micPermissionSkipped } = await chrome.storage.local.get([
      'micPermissionGranted',
      'micPermissionSkipped'
    ]);

    if (micPermissionGranted) {
      return true;
    }

    if (micPermissionSkipped) {
      return false;
    }

    // Try to query permission status
    const permissionStatus = await navigator.permissions.query({ name: 'microphone' }).catch(() => null);

    if (permissionStatus?.state === 'granted') {
      await chrome.storage.local.set({ micPermissionGranted: true });
      return true;
    }

    return false;
  } catch (error) {
    console.log('[SidePanel] Error checking mic permission:', error);
    return false;
  }
}

/**
 * Open mic permission request page in a new tab.
 * This is the workaround for side panels not being able to request mic permission directly.
 */
async function requestMicPermission() {
  const permissionUrl = chrome.runtime.getURL('src/sidepanel/request-mic.html');
  await chrome.tabs.create({ url: permissionUrl });
}

// Set up mic permission button handlers
if (requestMicBtnEl) {
  requestMicBtnEl.onclick = requestMicPermission;
}

if (skipMicBtnEl) {
  skipMicBtnEl.onclick = async () => {
    await chrome.storage.local.set({ micPermissionSkipped: true });
    selectedInputMode = 'text';
    showModeSelection();
  };
}

// ============================================
// Session Management
// ============================================

/**
 * Create session with selected mode.
 */
async function createSession(sessionType) {
  showLoading('Creating session...');

  // If voice mode selected, verify permission first
  if (selectedInputMode === 'voice') {
    const hasPermission = await checkMicPermission();
    if (!hasPermission) {
      showMicPermission();
      return;
    }
  }

  const apiMode = selectedInputMode === 'voice' ? 'pipeline' : 'text';
  console.log('[SidePanel] Creating session with mode:', apiMode, 'sessionType:', sessionType);

  try {
    const response = await chrome.runtime.sendMessage({
      type: 'CREATE_SESSION',
      prContext,
      mode: apiMode,
      sessionType,
    });

    console.log('[SidePanel] Create session response:', response);

    if (response.success) {
      currentSession = response.session;
      showChatInterface();
    } else {
      showConnectionError(response.error || 'Failed to create session');
    }
  } catch (error) {
    console.error('[SidePanel] Error creating session:', error);
    showConnectionError(error.message);
  }
}

/**
 * Show chat interface.
 */
function showChatInterface() {
  hideAll();
  chatInterfaceEl.style.display = 'flex';

  document.getElementById('chatPrBadge').textContent =
    `${prContext.owner}/${prContext.repo}#${prContext.number}`;

  const modeBadge = document.getElementById('modeBadge');
  modeBadge.textContent = currentSession.sessionType === 'author' ? 'Author' : 'Reviewer';
  modeBadge.className = `mode-badge ${currentSession.sessionType}`;

  const isVoiceMode = currentSession.inputMode === 'voice' || currentSession.mode === 'pipeline';
  if (micBtnEl) {
    micBtnEl.style.display = 'flex';
  }

  if (isVoiceMode) {
    messageInputEl.placeholder = 'Type or use mic for voice...';
    addMessage('system', 'Voice mode: Click mic to speak, responses will be read aloud');
  } else {
    messageInputEl.placeholder = 'Type a message... (Shift+Enter for new line)';
  }

  // Set up event listeners
  sendBtnEl.onclick = sendMessage;
  messageInputEl.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  messageInputEl.oninput = () => {
    messageInputEl.style.height = 'auto';
    messageInputEl.style.height = Math.min(messageInputEl.scrollHeight, 120) + 'px';
  };

  endSessionBtnEl.onclick = endSession;
  clearSelectionEl.onclick = clearSelection;
  micBtnEl.onclick = toggleRecording;

  // Flow mode handlers (only show button in voice mode for author)
  const isAuthorMode = currentSession.sessionType === 'author';
  if (flowModeBtnEl && isVoiceMode && isAuthorMode) {
    flowModeBtnEl.style.display = 'flex';
    flowModeBtnEl.onclick = toggleFlowMode;
  }
  if (flowEngageBtnEl) {
    flowEngageBtnEl.onclick = triggerFlowEngagement;
  }

  // Message listener is registered in init() - no need to add again
  checkExistingSelection();
  messageInputEl.focus();
}

/**
 * Check for existing text selection on the active tab.
 * If content script isn't responding, try to inject it.
 */
async function checkExistingSelection() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) return;

    // First try to contact existing content script
    try {
      const response = await chrome.tabs.sendMessage(tab.id, { type: 'GET_SELECTION' });
      if (response?.success && response.result?.hasSelection) {
        currentSelection = response.result;
        showSelectionHint(response.result.text);
        console.log('[SidePanel] Found existing selection:', response.result.text?.substring(0, 50));

        chrome.runtime.sendMessage({
          type: 'SELECTION_CHANGED',
          selection: response.result,
        }).catch(() => {});
      }
      return;
    } catch (error) {
      // Content script not responding - try to inject it
      console.log('[SidePanel] Content script not responding, attempting injection...');
    }

    // Try to inject content script
    if (tab.url?.includes('github.com') && tab.url?.includes('/pull/')) {
      try {
        await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          files: ['src/content/content-script.js'],
        });
        console.log('[SidePanel] Content script injected successfully');

        // Wait a moment for script to initialize, then retry
        await new Promise(resolve => setTimeout(resolve, 100));
        const response = await chrome.tabs.sendMessage(tab.id, { type: 'GET_SELECTION' });
        if (response?.success && response.result?.hasSelection) {
          currentSelection = response.result;
          showSelectionHint(response.result.text);
          console.log('[SidePanel] Found existing selection after injection:', response.result.text?.substring(0, 50));
        }
      } catch (injectError) {
        console.log('[SidePanel] Could not inject content script:', injectError.message);
      }
    }
  } catch (error) {
    console.log('[SidePanel] Could not check existing selection:', error.message);
  }
}

/**
 * Load and display conversation history.
 */
function loadConversationHistory(history) {
  if (!history || !Array.isArray(history)) return;

  chatMessagesEl.innerHTML = '';

  for (const msg of history) {
    if (msg.role === 'user') {
      addMessage('user', msg.content);
    } else if (msg.role === 'assistant') {
      addMessage('assistant', msg.content);
    }
  }
}

/**
 * Handle messages from service worker.
 */
function handleRuntimeMessage(message, sender, sendResponse) {
  console.log('[SidePanel] Received message:', message.type, message);

  if (message.type === 'WS_EVENT') {
    handleWsEvent(message.event);
  } else if (message.type === 'SELECTION_CHANGED') {
    console.log('[SidePanel] Selection changed:', message.selection?.text?.substring(0, 50));
    handleSelectionChanged(message.selection);
  } else if (message.type === 'MIC_PERMISSION_GRANTED') {
    console.log('[SidePanel] Mic permission granted via permission page');
    selectedInputMode = 'voice';
    showModeSelection();
  } else if (message.type === 'MIC_PERMISSION_SKIPPED') {
    console.log('[SidePanel] Mic permission skipped');
    selectedInputMode = 'text';
    showModeSelection();
  }

  // Return false to indicate synchronous handling (no sendResponse needed)
  return false;
}

/**
 * Handle WebSocket events from service worker.
 */
function handleWsEvent(event) {
  console.log('[SidePanel] WS event:', event.type);

  switch (event.type) {
    case 'ready':
      updateConnectionStatus(true);
      if (event.audio_config) {
        inputSampleRate = event.audio_config.input_sample_rate || 24000;
        outputSampleRate = event.audio_config.output_sample_rate || 16000;
        console.log(`[SidePanel] Audio config: input=${inputSampleRate}Hz, output=${outputSampleRate}Hz`);
      }
      if (event.conversation_history) {
        loadConversationHistory(event.conversation_history);
      }
      if (event.data?.greeting) {
        addMessage('assistant', event.data.greeting);
      }
      break;

    case 'agent_response':
      console.log('[SidePanel] Agent response event:', JSON.stringify(event).substring(0, 500));
      removeTypingIndicator();
      hideToolActivity();
      const responseText = event.data?.text || event.text || event.data?.content || event.content || event.message;
      if (responseText) {
        addMessage('assistant', responseText);
      } else {
        console.warn('[SidePanel] No text found in agent_response:', event);
      }
      break;

    case 'agent_message':
      console.log('[SidePanel] Agent message event:', JSON.stringify(event).substring(0, 500));
      removeTypingIndicator();
      hideToolActivity();
      const msgText = event.data?.text || event.text || event.data?.content || event.content;
      if (msgText) {
        addMessage('assistant', msgText);
      }
      break;

    case 'agent_thinking':
      showTypingIndicator();
      break;

    case 'tool_call':
      showToolActivity(formatToolName(event.data?.tool || event.tool));
      break;

    case 'tool_result':
      console.log('[SidePanel] Tool result:', event);
      hideToolActivity();
      break;

    case 'transcript':
      console.log('[SidePanel] Transcript event:', event);
      const transcriptRole = event.data?.role || event.role;
      const transcriptText = event.data?.text || event.text || event.transcript;

      if (transcriptText) {
        if (transcriptRole === 'assistant') {
          removeTypingIndicator();
          hideToolActivity();
          addMessage('assistant', transcriptText);
        } else {
          addMessage('user', transcriptText);
        }
      }
      break;

    case 'error':
      removeTypingIndicator();
      hideToolActivity();
      addMessage('system', `Error: ${event.data?.error || event.error || 'Unknown error'}`);
      break;

    case 'disconnected':
      updateConnectionStatus(false);
      if (event.permanent) {
        addMessage('system', 'Disconnected from server');
      }
      break;

    case 'connected':
      updateConnectionStatus(true);
      break;

    case 'audio_start':
      console.log('[SidePanel] Audio stream starting');
      handleAudioStart();
      break;

    case 'audio_end':
      console.log('[SidePanel] Audio stream ended');
      handleAudioEnd();
      break;

    case 'audio_chunk':
      if (event.data?.audio) {
        playAudio(event.data.audio);
      }
      break;

    case 'audio':
      if (event.audio) {
        playAudio(event.audio);
      }
      break;

    // Flow mode events
    case 'flow_mode_started':
      console.log('[SidePanel] Flow mode started');
      isFlowMode = true;
      updateFlowModeUI(true);
      break;

    case 'flow_mode_ended':
      console.log('[SidePanel] Flow mode ended');
      isFlowMode = false;
      updateFlowModeUI(false);
      break;

    case 'flow_acknowledgement':
      console.log('[SidePanel] Flow acknowledgement:', event.data?.text);
      // Acknowledgement audio is handled by audio events
      break;

    case 'flow_engagement_signal':
      console.log('[SidePanel] Flow engagement triggered', event.data);
      // UI will update when flow_mode_ended fires
      break;

    case 'flow_transcript_chunk':
      console.log('[SidePanel] Flow transcript:', event.data?.text?.substring(0, 50));
      // Could show live transcript preview here
      break;

    default:
      console.log('[SidePanel] Unhandled WS event type:', event.type, event);
      break;
  }
}

/**
 * Handle selection changes from content script.
 */
function handleSelectionChanged(selection) {
  console.log('[SidePanel] handleSelectionChanged called:', selection);
  if (selection && selection.hasSelection && selection.text) {
    currentSelection = selection;
    showSelectionHint(selection.text);
    console.log('[SidePanel] Selection hint shown for:', selection.text.substring(0, 50));
  } else {
    console.log('[SidePanel] Clearing selection');
    clearSelection();
  }
}

// ============================================
// Flow Mode Functions
// ============================================

/**
 * Toggle flow mode on/off.
 */
async function toggleFlowMode() {
  if (isFlowMode) {
    // Turn off flow mode
    console.log('[SidePanel] Stopping flow mode');
    chrome.runtime.sendMessage({
      type: 'FLOW_STOP',
    }).catch(err => console.error('[SidePanel] Error stopping flow mode:', err));
  } else {
    // Turn on flow mode - must be recording
    const hasPermission = await checkMicPermission();
    if (!hasPermission) {
      showMicPermission();
      return;
    }

    console.log('[SidePanel] Starting flow mode');

    // Start recording if not already
    if (!isRecording) {
      await startRecording();
    }

    // Send flow mode start message
    chrome.runtime.sendMessage({
      type: 'FLOW_START',
    }).catch(err => console.error('[SidePanel] Error starting flow mode:', err));
  }
}

/**
 * Trigger engagement in flow mode (ready for questions).
 */
function triggerFlowEngagement() {
  if (!isFlowMode) {
    console.log('[SidePanel] Not in flow mode, cannot engage');
    return;
  }

  console.log('[SidePanel] Triggering flow engagement');

  // Stop recording first
  if (isRecording) {
    stopRecording();
  }

  // Send engagement message
  chrome.runtime.sendMessage({
    type: 'FLOW_ENGAGE',
  }).catch(err => console.error('[SidePanel] Error triggering engagement:', err));
}

/**
 * Update flow mode UI state.
 */
function updateFlowModeUI(enabled) {
  if (flowModeIndicatorEl) {
    if (enabled) {
      flowModeIndicatorEl.classList.add('active');
    } else {
      flowModeIndicatorEl.classList.remove('active');
    }
  }

  if (flowModeBtnEl) {
    if (enabled) {
      flowModeBtnEl.classList.add('active');
      flowModeBtnEl.title = 'Exit Flow Mode';
    } else {
      flowModeBtnEl.classList.remove('active');
      flowModeBtnEl.title = 'Enter Flow Mode (continuous capture)';
    }
  }

  // Hide/show regular mic button based on flow mode
  if (micBtnEl) {
    micBtnEl.style.display = enabled ? 'none' : 'flex';
  }
}

/**
 * Send chat message.
 */
async function sendMessage() {
  const text = messageInputEl.value.trim();
  if (!text) return;

  messageInputEl.value = '';
  messageInputEl.style.height = 'auto';

  addMessage('user', text);
  showTypingIndicator();

  const selectionToSend = currentSelection;

  try {
    await chrome.runtime.sendMessage({
      type: 'SEND_MESSAGE',
      text,
      selection: selectionToSend,
    });
  } catch (error) {
    console.error('[SidePanel] Error sending message:', error);
    removeTypingIndicator();
    addMessage('system', 'Failed to send message');
  }
}

/**
 * Add message to chat.
 */
function addMessage(role, text) {
  const messageEl = document.createElement('div');
  messageEl.className = `message ${role}`;

  let formattedText = escapeHtml(text);

  formattedText = formattedText.replace(/```(\w*)\n?([\s\S]*?)```/g, (match, lang, code) => {
    return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
  });

  formattedText = formattedText.replace(/`([^`]+)`/g, '<code>$1</code>');
  formattedText = formattedText.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  formattedText = formattedText.replace(/\n/g, '<br>');

  messageEl.innerHTML = `<div class="message-content">${formattedText}</div>`;
  chatMessagesEl.appendChild(messageEl);
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

/**
 * Show typing indicator.
 */
function showTypingIndicator() {
  if (document.getElementById('typingIndicator')) return;

  const indicator = document.createElement('div');
  indicator.id = 'typingIndicator';
  indicator.className = 'message assistant typing';
  indicator.innerHTML = `
    <div class="message-content">
      <div class="typing-dots">
        <span></span><span></span><span></span>
      </div>
    </div>
  `;
  chatMessagesEl.appendChild(indicator);
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

/**
 * Remove typing indicator.
 */
function removeTypingIndicator() {
  document.getElementById('typingIndicator')?.remove();
}

/**
 * Show tool activity indicator.
 */
function showToolActivity(toolName) {
  toolActivityEl.style.display = 'flex';
  toolNameEl.textContent = toolName;
}

/**
 * Hide tool activity indicator.
 */
function hideToolActivity() {
  toolActivityEl.style.display = 'none';
}

/**
 * Format tool name for display.
 */
function formatToolName(toolName) {
  const toolLabels = {
    'query_rag': 'Searching knowledge base...',
    'query_knowledge_base': 'Searching knowledge base...',
    'store_explanation': 'Storing explanation...',
  };
  return toolLabels[toolName] || `Running ${toolName}...`;
}

/**
 * Show selection hint.
 */
function showSelectionHint(text) {
  console.log('[SidePanel] showSelectionHint called, element:', selectionHintEl, 'visible:', chatInterfaceEl.style.display);
  if (selectionHintEl && chatInterfaceEl.style.display !== 'none') {
    selectionHintEl.style.display = 'flex';
    selectionTextEl.textContent = text.length > 50 ? text.substring(0, 50) + '...' : text;
    console.log('[SidePanel] Selection hint displayed');
  } else {
    console.log('[SidePanel] Cannot show selection hint - chat interface not visible or element missing');
  }
}

/**
 * Clear selection hint.
 */
function clearSelection() {
  currentSelection = null;
  selectionHintEl.style.display = 'none';
}

/**
 * Update connection status indicator.
 */
function updateConnectionStatus(connected) {
  connectionStatusEl.className = `connection-status ${connected ? '' : 'disconnected'}`;
  connectionStatusEl.title = connected ? 'Connected' : 'Disconnected';
}

/**
 * End current session.
 */
async function endSession() {
  try {
    await chrome.runtime.sendMessage({ type: 'END_SESSION' });
    currentSession = null;
    chatMessagesEl.innerHTML = '';
    // Keep message listener active for selection changes
    showModeSelection();
  } catch (error) {
    console.error('[SidePanel] Error ending session:', error);
  }
}

/**
 * Escape HTML characters.
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ============================================================================
// Audio Recording & Playback
// ============================================================================

/**
 * Toggle recording on/off.
 */
async function toggleRecording() {
  console.log('[SidePanel] toggleRecording, current isRecording:', isRecording);
  if (isRecording) {
    stopRecording();
  } else {
    // Check mic permission before recording
    const hasPermission = await checkMicPermission();
    if (hasPermission) {
      startRecording();
    } else {
      showMicPermission();
    }
  }
}

/**
 * Start voice recognition using browser SpeechRecognition API.
 * Sends transcripts as text messages — no audio streaming to server.
 */
async function startRecording() {
  if (isRecording) return;

  stopAudioPlayback('mic-button');

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    addMessage('system', 'Speech recognition is not supported in this browser.');
    return;
  }

  // Check mic permission (still needed for SpeechRecognition)
  try {
    const permissionStatus = await navigator.permissions.query({ name: 'microphone' }).catch(() => null);
    if (permissionStatus?.state === 'denied') {
      addMessage('system', 'Microphone permission denied. Please grant permission first.');
      showMicPermission();
      return;
    }
  } catch (e) {
    // permissions.query may not support microphone — continue anyway
  }

  speechRecognition = new SpeechRecognition();
  speechRecognition.continuous = true;
  speechRecognition.interimResults = true;
  speechRecognition.lang = 'en-US';

  let finalTranscript = '';

  speechRecognition.onresult = (event) => {
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) {
        finalTranscript += result[0].transcript + ' ';
      } else {
        interim = result[0].transcript;
      }
    }

    // Show interim transcript in the listening indicator
    if (interim) {
      listeningIndicatorEl.textContent = interim;
    }
  };

  speechRecognition.onend = () => {
    // Send accumulated final transcript when recognition stops
    const text = finalTranscript.trim();
    if (text && isRecording) {
      console.log('[SidePanel] Sending speech transcript:', text.substring(0, 80));

      // Prepend selection context if available
      let messageText = text;
      if (currentSelection && currentSelection.hasSelection) {
        const selText = currentSelection.text || '';
        const filePath = currentSelection.context?.filePath || '';
        const fileInfo = filePath ? ` (from ${filePath})` : '';
        messageText = `Current diff selection${fileInfo}:\n\`\`\`\n${selText}\n\`\`\`\n\nUser question: ${text}`;
      }

      chrome.runtime.sendMessage({
        type: 'SEND_MESSAGE',
        text: messageText,
      }).catch(() => {});

      addMessage('user', text);
      finalTranscript = '';
    }

    // Auto-restart if still in recording mode (continuous listening)
    if (isRecording) {
      try {
        speechRecognition.start();
      } catch (e) {
        // Already started or other error — ignore
      }
    }
  };

  speechRecognition.onerror = (event) => {
    console.error('[SidePanel] Speech recognition error:', event.error);
    if (event.error === 'not-allowed') {
      addMessage('system', 'Microphone access denied. Please grant permission.');
      showMicPermission();
      stopRecording();
    } else if (event.error === 'no-speech') {
      // Normal — just means silence detected, will auto-restart
    } else if (event.error === 'aborted') {
      // User stopped recording
    } else {
      addMessage('system', `Speech error: ${event.error}`);
    }
  };

  try {
    speechRecognition.start();
    await chrome.storage.local.set({ micPermissionGranted: true });

    isRecording = true;
    micBtnEl.classList.add('recording');
    listeningIndicatorEl.classList.add('active');
    listeningIndicatorEl.textContent = 'Listening...';
    console.log('[SidePanel] Browser speech recognition started');

    if (currentSelection && currentSelection.hasSelection) {
      console.log('[SidePanel] Selection context available for voice mode');
    }
  } catch (error) {
    console.error('[SidePanel] Speech recognition start error:', error);
    addMessage('system', `Could not start speech recognition: ${error.message}`);
  }
}

/**
 * Stop voice recognition.
 */
function stopRecording() {
  if (!isRecording) return;

  isRecording = false;
  micBtnEl.classList.remove('recording');
  listeningIndicatorEl.classList.remove('active');
  listeningIndicatorEl.textContent = '';

  if (speechRecognition) {
    speechRecognition.stop();
    speechRecognition = null;
  }

  console.log('[SidePanel] Speech recognition stopped');
}

/**
 * Handle audio stream start from server.
 */
function handleAudioStart() {
  for (const source of activeAudioSources) {
    try { source.stop(); } catch (e) {}
  }
  activeAudioSources = [];

  if (playbackContext && playbackContext.state !== 'closed') {
    if (masterGain) masterGain.gain.value = 0;
    playbackContext.close().catch(() => {});
    playbackContext = null;
    masterGain = null;
  }

  audioQueue = [];
  scheduledCount = 0;
  isPlaying = false;
  audioStreamEnded = false;
  scheduledEndTime = 0;
}

/**
 * Handle audio stream end from server.
 */
function handleAudioEnd() {
  audioStreamEnded = true;

  if (!isPlaying && audioQueue.length > 0) {
    startScheduledPlayback();
  } else if (isPlaying && audioQueue.length > 0 && scheduledCount < MAX_SCHEDULED_AHEAD) {
    scheduleQueuedAudio();
  }
}

/**
 * Play audio chunk (base64 PCM16).
 */
async function playAudio(base64Audio) {
  const binaryString = atob(base64Audio);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }

  audioQueue.push(bytes.buffer);

  if (!isPlaying && (audioQueue.length >= MIN_BUFFER_CHUNKS || audioStreamEnded)) {
    await startScheduledPlayback();
  } else if (isPlaying && scheduledCount < MAX_SCHEDULED_AHEAD) {
    scheduleOneChunk();
  }
}

/**
 * Start scheduled audio playback.
 */
async function startScheduledPlayback() {
  if (isPlaying) return;

  try {
    if (!playbackContext || playbackContext.state === 'closed') {
      playbackContext = new AudioContext({ sampleRate: outputSampleRate });
      masterGain = playbackContext.createGain();
      masterGain.connect(playbackContext.destination);
    }

    if (masterGain) {
      masterGain.gain.value = 1;
    }

    if (playbackContext.state === 'suspended') {
      await playbackContext.resume();
    }

    isPlaying = true;
    scheduledEndTime = playbackContext.currentTime + 0.02;
    scheduleQueuedAudio();

  } catch (error) {
    console.error('[SidePanel] Failed to start playback:', error);
    isPlaying = false;
  }
}

/**
 * Schedule one audio chunk for playback.
 */
function scheduleOneChunk() {
  if (audioQueue.length === 0 || !playbackContext || scheduledCount >= MAX_SCHEDULED_AHEAD) {
    return false;
  }

  const audioData = audioQueue.shift();

  try {
    const pcm16 = new Int16Array(audioData);
    const float32 = new Float32Array(pcm16.length);
    for (let i = 0; i < pcm16.length; i++) {
      float32[i] = pcm16[i] / 32768.0;
    }

    const audioBuffer = playbackContext.createBuffer(1, float32.length, outputSampleRate);
    audioBuffer.getChannelData(0).set(float32);

    const source = playbackContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(masterGain || playbackContext.destination);

    activeAudioSources.push(source);
    scheduledCount++;

    source.onended = () => {
      const idx = activeAudioSources.indexOf(source);
      if (idx > -1) activeAudioSources.splice(idx, 1);
      scheduledCount--;

      if (audioQueue.length > 0) {
        scheduleOneChunk();
      } else if (scheduledCount === 0) {
        onPlaybackComplete();
      }
    };

    const startTime = Math.max(scheduledEndTime, playbackContext.currentTime);
    source.start(startTime);
    scheduledEndTime = startTime + audioBuffer.duration;

    return true;

  } catch (error) {
    console.error('[SidePanel] Error scheduling audio chunk:', error);
    return false;
  }
}

/**
 * Schedule all queued audio chunks.
 */
function scheduleQueuedAudio() {
  while (scheduledCount < MAX_SCHEDULED_AHEAD && audioQueue.length > 0) {
    if (!scheduleOneChunk()) break;
  }
}

/**
 * Called when playback completes.
 */
function onPlaybackComplete() {
  if (!isPlaying) return;
  console.log('[SidePanel] Playback complete');
  isPlaying = false;
}

/**
 * Stop audio playback.
 */
function stopAudioPlayback(caller = 'unknown') {
  console.log(`[SidePanel] stopAudioPlayback called by: ${caller}`);

  if (playbackContext && playbackContext.state === 'running') {
    playbackContext.suspend().catch(() => {});
  }

  if (masterGain) {
    try {
      const now = playbackContext?.currentTime || 0;
      masterGain.gain.cancelScheduledValues(now);
      masterGain.gain.setValueAtTime(0, now);
      masterGain.disconnect();
    } catch (e) {}
  }

  for (const source of activeAudioSources) {
    try {
      source.onended = null;
      source.disconnect();
      source.stop();
    } catch (e) {}
  }
  activeAudioSources = [];

  audioQueue = [];
  scheduledCount = 0;
  isPlaying = false;
  audioStreamEnded = true;
  scheduledEndTime = 0;

  if (playbackContext && playbackContext.state !== 'closed') {
    playbackContext.close().catch(() => {});
    playbackContext = null;
    masterGain = null;
  }
}

// Set up retry button
retryBtnEl?.addEventListener('click', () => {
  init();
});

// Initialize
init();
