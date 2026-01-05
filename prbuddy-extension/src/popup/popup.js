/**
 * PR Buddy Extension Popup
 *
 * Main UI for the Chrome extension.
 * Handles mode selection, chat interface, and message display.
 */

// State
let currentSession = null;
let prContext = null;
let currentSelection = null;
let selectedInputMode = 'text'; // 'text' or 'voice'

// Audio state
let isRecording = false;
let isPlaying = false;
let recordContext = null;
let mediaStream = null;
let audioWorklet = null;
let playbackContext = null;
let masterGain = null;
let audioQueue = [];
let scheduledEndTime = 0;
let scheduledCount = 0;
let activeAudioSources = [];
let audioStreamEnded = false;

// Audio config (set by server)
let inputSampleRate = 24000;
let outputSampleRate = 16000;
const MIN_BUFFER_CHUNKS = 2;
const MAX_SCHEDULED_AHEAD = 2;

// Silence detection config
const SILENCE_THRESHOLD = 0.01; // RMS threshold for silence detection
const SILENCE_CHUNKS_BEFORE_SKIP = 5; // Allow some silent chunks through
let consecutiveSilentChunks = 0;

// DOM elements
const loadingEl = document.getElementById('loading');
const notPrPageEl = document.getElementById('not-pr-page');
const connectionErrorEl = document.getElementById('connection-error');
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

/**
 * Initialize popup.
 */
async function init() {
  console.log('[Popup] Initializing...');

  // Check for existing session first
  try {
    const sessionResponse = await chrome.runtime.sendMessage({ type: 'GET_SESSION' });
    console.log('[Popup] Session response:', sessionResponse);

    if (sessionResponse.success && sessionResponse.session) {
      currentSession = sessionResponse.session;
      prContext = currentSession.prContext;
      showChatInterface();
      return;
    }
  } catch (error) {
    console.error('[Popup] Error getting session:', error);
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
      console.log('[Popup] No active tab');
      showNotPrPage();
      return;
    }

    console.log('[Popup] Active tab:', tab.url);

    // Check if URL looks like a GitHub PR
    if (!tab.url?.match(/github\.com\/[^/]+\/[^/]+\/pull\/\d+/)) {
      showNotPrPage();
      return;
    }

    // Try to get context from content script
    try {
      const response = await chrome.tabs.sendMessage(tab.id, { type: 'GET_PR_CONTEXT' });
      console.log('[Popup] PR context response:', response);

      if (response.success && response.context) {
        prContext = response.context;
        showModeSelection();
      } else {
        showNotPrPage();
      }
    } catch (error) {
      console.log('[Popup] Content script not ready, parsing URL directly');

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
    console.error('[Popup] Error detecting PR context:', error);
    showNotPrPage();
  }
}

/**
 * Hide all state panels.
 */
function hideAll() {
  loadingEl.style.display = 'none';
  notPrPageEl.style.display = 'none';
  connectionErrorEl.style.display = 'none';
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

  voiceModeBtn.onclick = () => {
    selectedInputMode = 'voice';
    voiceModeBtn.classList.add('active');
    textModeBtn.classList.remove('active');
  };

  // Set up mode button handlers
  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.onclick = () => {
      const sessionType = btn.dataset.mode;
      createSession(sessionType);
    };
  });
}

/**
 * Create session with selected mode.
 */
async function createSession(sessionType) {
  showLoading('Creating session...');

  // Determine API mode based on selected input mode
  // 'text' = text chat only, 'voice' = voice with TTS/STT via pipeline
  const apiMode = selectedInputMode === 'voice' ? 'pipeline' : 'text';
  console.log('[Popup] Creating session with mode:', apiMode, 'sessionType:', sessionType);

  try {
    const response = await chrome.runtime.sendMessage({
      type: 'CREATE_SESSION',
      prContext,
      mode: apiMode,
      sessionType,
    });

    console.log('[Popup] Create session response:', response);

    if (response.success) {
      currentSession = response.session;
      showChatInterface();
    } else {
      showConnectionError(response.error || 'Failed to create session');
    }
  } catch (error) {
    console.error('[Popup] Error creating session:', error);
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

  // Show mic button - always available (user might want voice input in any mode)
  // In voice/pipeline mode, TTS responses will also play
  const isVoiceMode = currentSession.inputMode === 'voice' || currentSession.mode === 'pipeline';
  if (micBtnEl) {
    micBtnEl.style.display = 'flex'; // Always show mic
  }

  // Update placeholder based on mode
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

  // Auto-resize textarea
  messageInputEl.oninput = () => {
    messageInputEl.style.height = 'auto';
    messageInputEl.style.height = Math.min(messageInputEl.scrollHeight, 120) + 'px';
  };

  endSessionBtnEl.onclick = endSession;
  clearSelectionEl.onclick = clearSelection;
  micBtnEl.onclick = toggleRecording;

  // Listen for WebSocket events from service worker
  chrome.runtime.onMessage.addListener(handleRuntimeMessage);

  // Check for existing selection on the page
  checkExistingSelection();

  // Focus input
  messageInputEl.focus();
}

/**
 * Check for existing text selection on the active tab.
 * Called when popup opens to capture any pre-existing selection.
 */
async function checkExistingSelection() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) return;

    // Request current selection from content script
    const response = await chrome.tabs.sendMessage(tab.id, { type: 'GET_SELECTION' });
    if (response?.success && response.result?.hasSelection) {
      currentSelection = response.result;
      showSelectionHint(response.result.text);
      console.log('[Popup] Found existing selection:', response.result.text?.substring(0, 50));

      // Also cache it in service worker for tool requests
      chrome.runtime.sendMessage({
        type: 'SELECTION_CHANGED',
        selection: response.result,
      }).catch(() => {});
    }
  } catch (error) {
    console.log('[Popup] Could not check existing selection:', error.message);
  }
}

/**
 * Load and display conversation history.
 */
function loadConversationHistory(history) {
  if (!history || !Array.isArray(history)) return;

  // Clear existing messages
  chatMessagesEl.innerHTML = '';

  // Add each message from history
  for (const msg of history) {
    if (msg.role === 'user') {
      addMessage('user', msg.content);
    } else if (msg.role === 'assistant') {
      addMessage('assistant', msg.content);
    }
    // Skip system messages
  }
}

/**
 * Handle messages from service worker.
 */
function handleRuntimeMessage(message, sender, sendResponse) {
  console.log('[Popup] Received message:', message.type);

  if (message.type === 'WS_EVENT') {
    handleWsEvent(message.event);
  } else if (message.type === 'SELECTION_CHANGED') {
    handleSelectionChanged(message.selection);
  }
}

/**
 * Handle WebSocket events from service worker.
 */
function handleWsEvent(event) {
  console.log('[Popup] WS event:', event.type);

  switch (event.type) {
    case 'ready':
      updateConnectionStatus(true);
      // Get audio config from server
      if (event.audio_config) {
        inputSampleRate = event.audio_config.input_sample_rate || 24000;
        outputSampleRate = event.audio_config.output_sample_rate || 16000;
        console.log(`[Popup] Audio config: input=${inputSampleRate}Hz, output=${outputSampleRate}Hz`);
      }
      // Load conversation history if available
      if (event.conversation_history) {
        loadConversationHistory(event.conversation_history);
      }
      if (event.data?.greeting) {
        addMessage('assistant', event.data.greeting);
      }
      break;

    case 'agent_response':
      console.log('[Popup] Agent response event:', JSON.stringify(event).substring(0, 500));
      removeTypingIndicator();
      hideToolActivity();
      // Handle various response formats from server
      const responseText = event.data?.text || event.text || event.data?.content || event.content || event.message;
      if (responseText) {
        addMessage('assistant', responseText);
      } else {
        console.warn('[Popup] No text found in agent_response:', event);
      }
      break;

    case 'agent_message':
      // Alternative event name for agent responses
      console.log('[Popup] Agent message event:', JSON.stringify(event).substring(0, 500));
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
      // Hide tool activity when tool completes
      console.log('[Popup] Tool result:', event);
      hideToolActivity();
      break;

    case 'transcript':
      // Show transcribed speech - both user (STT input) and assistant (TTS response)
      console.log('[Popup] Transcript event:', event);
      const transcriptRole = event.data?.role || event.role;
      const transcriptText = event.data?.text || event.text || event.transcript;

      if (transcriptText) {
        if (transcriptRole === 'assistant') {
          removeTypingIndicator();
          hideToolActivity();
          addMessage('assistant', transcriptText);
        } else {
          // Default to 'user' for backwards compatibility
          addMessage('user', transcriptText);
        }
      }
      break;

    // Note: 'user_message' handler removed - text mode displays message immediately
    // in sendMessage(), voice mode uses 'transcript' events for user speech

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
      console.log('[Popup] Audio stream starting');
      handleAudioStart();
      break;

    case 'audio_end':
      console.log('[Popup] Audio stream ended');
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

    default:
      // Log any unhandled events for debugging
      console.log('[Popup] Unhandled WS event type:', event.type, event);
      break;
  }
}

/**
 * Handle selection changes from content script.
 */
function handleSelectionChanged(selection) {
  if (selection.hasSelection && selection.text) {
    currentSelection = selection;
    showSelectionHint(selection.text);
  } else {
    // Selection was cleared on the page
    clearSelection();
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

  // Send current selection with message (keep it for subsequent messages)
  const selectionToSend = currentSelection;

  try {
    await chrome.runtime.sendMessage({
      type: 'SEND_MESSAGE',
      text,
      selection: selectionToSend,  // Include selection with message
    });
  } catch (error) {
    console.error('[Popup] Error sending message:', error);
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

  // Simple markdown-like formatting
  let formattedText = escapeHtml(text);

  // Code blocks
  formattedText = formattedText.replace(/```(\w*)\n?([\s\S]*?)```/g, (match, lang, code) => {
    return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
  });

  // Inline code
  formattedText = formattedText.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Bold
  formattedText = formattedText.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  // Newlines
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
  selectionHintEl.style.display = 'flex';
  selectionTextEl.textContent = text.length > 50 ? text.substring(0, 50) + '...' : text;
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
    chrome.runtime.onMessage.removeListener(handleRuntimeMessage);
    showModeSelection();
  } catch (error) {
    console.error('[Popup] Error ending session:', error);
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
function toggleRecording() {
  console.log('[Popup] toggleRecording, current isRecording:', isRecording);
  if (isRecording) {
    stopRecording();
  } else {
    startRecording();
  }
}

/**
 * Start audio recording.
 */
async function startRecording() {
  if (isRecording) return;

  // Stop any playback when user starts recording
  stopAudioPlayback('mic-button');

  try {
    // Check if we have permission first
    const permissionStatus = await navigator.permissions.query({ name: 'microphone' }).catch(() => null);

    if (permissionStatus?.state === 'denied') {
      addMessage('system', 'Microphone permission denied. Please enable it in Chrome settings for this extension.');
      showMicPermissionHelp();
      return;
    }

    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: inputSampleRate,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    recordContext = new AudioContext({ sampleRate: inputSampleRate });
    const source = recordContext.createMediaStreamSource(mediaStream);

    // Use AudioWorklet for continuous PCM16 streaming
    if (recordContext.audioWorklet) {
      await setupAudioWorklet(source);
    } else {
      setupScriptProcessor(source);
    }

    isRecording = true;
    micBtnEl.classList.add('recording');
    listeningIndicatorEl.classList.add('active');
    console.log('[Popup] Recording started');

    // Send any current selection to server for voice mode
    // This way selection is available when STT completes
    // Keep selection in memory for subsequent messages
    if (currentSelection && currentSelection.hasSelection) {
      console.log('[Popup] Sending selection for voice mode');
      chrome.runtime.sendMessage({
        type: 'SEND_SELECTION',
        selection: currentSelection,
      }).catch(() => {});
    }

  } catch (error) {
    console.error('[Popup] Recording error:', error);

    if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
      addMessage('system', 'Microphone access denied. Click the mic icon in the address bar to enable.');
      showMicPermissionHelp();
    } else if (error.name === 'NotFoundError') {
      addMessage('system', 'No microphone found. Please connect a microphone.');
    } else {
      addMessage('system', `Microphone error: ${error.message}`);
    }
  }
}

/**
 * Show help message for microphone permission.
 */
function showMicPermissionHelp() {
  // Create a temporary help message
  const helpDiv = document.createElement('div');
  helpDiv.className = 'message system';
  helpDiv.innerHTML = `
    <strong>To enable microphone:</strong><br>
    1. Click the puzzle icon in Chrome toolbar<br>
    2. Click the three dots next to PR Buddy<br>
    3. Select "Site settings"<br>
    4. Allow microphone access
  `;
  chatMessagesEl.appendChild(helpDiv);
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

/**
 * Set up AudioWorklet for recording.
 */
async function setupAudioWorklet(source) {
  try {
    // Load the processor module from extension files (not blob URL due to CSP)
    const processorUrl = chrome.runtime.getURL('src/popup/audio-processor.js');
    console.log('[Popup] Loading audio processor from:', processorUrl);

    await recordContext.audioWorklet.addModule(processorUrl);
    audioWorklet = new AudioWorkletNode(recordContext, 'pcm-processor');

    let audioChunksSent = 0;

    audioWorklet.port.onmessage = async (e) => {
      if (!isRecording) return;

      const float32 = e.data.audio;

      // Calculate RMS for silence detection
      let sumSquares = 0;
      for (let i = 0; i < float32.length; i++) {
        sumSquares += float32[i] * float32[i];
      }
      const rms = Math.sqrt(sumSquares / float32.length);

      // Skip if silent (but allow some silent chunks through for natural pauses)
      if (rms < SILENCE_THRESHOLD) {
        consecutiveSilentChunks++;
        if (consecutiveSilentChunks > SILENCE_CHUNKS_BEFORE_SKIP) {
          return; // Skip this silent chunk
        }
      } else {
        consecutiveSilentChunks = 0;
      }

      const pcm16 = new Int16Array(float32.length);
      for (let i = 0; i < float32.length; i++) {
        const s = Math.max(-1, Math.min(1, float32[i]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }

      const base64 = btoa(String.fromCharCode(...new Uint8Array(pcm16.buffer)));

      // Send audio to service worker
      try {
        await chrome.runtime.sendMessage({
          type: 'SEND_AUDIO',
          audio: base64,
        });
        audioChunksSent++;
        if (audioChunksSent === 1 || audioChunksSent % 25 === 0) {
          console.log(`[Popup] Sent audio chunk #${audioChunksSent} (rms: ${rms.toFixed(4)})`);
        }
      } catch (err) {
        console.error('[Popup] Error sending audio:', err);
      }
    };

    source.connect(audioWorklet);
  } catch (err) {
    console.error('[Popup] AudioWorklet setup failed:', err);
    // Fall back to ScriptProcessor
    console.log('[Popup] Falling back to ScriptProcessor');
    setupScriptProcessor(source);
  }
}

/**
 * Fallback ScriptProcessor for older browsers.
 */
function setupScriptProcessor(source) {
  const processor = recordContext.createScriptProcessor(4096, 1, 1);

  processor.onaudioprocess = async (e) => {
    if (!isRecording) return;

    const inputData = e.inputBuffer.getChannelData(0);
    const pcm16 = new Int16Array(inputData.length);
    for (let i = 0; i < inputData.length; i++) {
      const s = Math.max(-1, Math.min(1, inputData[i]));
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }

    const base64 = btoa(String.fromCharCode(...new Uint8Array(pcm16.buffer)));

    try {
      await chrome.runtime.sendMessage({
        type: 'SEND_AUDIO',
        audio: base64,
      });
    } catch (err) {
      console.error('[Popup] Error sending audio:', err);
    }
  };

  source.connect(processor);
  processor.connect(recordContext.destination);
}

/**
 * Stop audio recording.
 */
function stopRecording() {
  if (!isRecording) return;

  isRecording = false;
  consecutiveSilentChunks = 0; // Reset silence counter
  micBtnEl.classList.remove('recording');
  listeningIndicatorEl.classList.remove('active');

  if (mediaStream) {
    mediaStream.getTracks().forEach(track => track.stop());
    mediaStream = null;
  }

  if (audioWorklet) {
    audioWorklet.disconnect();
    audioWorklet = null;
  }

  if (recordContext && recordContext.state !== 'closed') {
    recordContext.close();
    recordContext = null;
  }

  console.log('[Popup] Recording stopped');
}

/**
 * Handle audio stream start from server.
 */
function handleAudioStart() {
  // Stop any existing playback
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
    console.error('[Popup] Failed to start playback:', error);
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
    console.error('[Popup] Error scheduling audio chunk:', error);
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
  console.log('[Popup] Playback complete');
  isPlaying = false;
}

/**
 * Stop audio playback.
 */
function stopAudioPlayback(caller = 'unknown') {
  console.log(`[Popup] stopAudioPlayback called by: ${caller}`);

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
