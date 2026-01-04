/**
 * Shared constants for PR Buddy extension.
 */

// Backend configuration
export const API_BASE = 'http://localhost:8000';
export const WS_BASE = 'ws://localhost:8000';

// Message types - Extension internal
export const MSG = {
  // Popup <-> Service Worker
  CREATE_SESSION: 'CREATE_SESSION',
  SEND_MESSAGE: 'SEND_MESSAGE',
  SEND_AUDIO: 'SEND_AUDIO',
  GET_SESSION: 'GET_SESSION',
  END_SESSION: 'END_SESSION',
  TOOL_RESPONSE: 'TOOL_RESPONSE',
  WS_EVENT: 'WS_EVENT',

  // Content Script <-> Popup/Service Worker
  GET_PR_CONTEXT: 'GET_PR_CONTEXT',
  GET_SELECTION: 'GET_SELECTION',
  SELECTION_CHANGED: 'SELECTION_CHANGED',
  PING: 'PING',
};

// WebSocket event types from backend
export const WS_EVENTS = {
  READY: 'ready',
  AGENT_RESPONSE: 'agent_response',
  AGENT_THINKING: 'agent_thinking',
  TOOL_CALL: 'tool_call',
  TOOL_RESULT: 'tool_result',
  TOOL_REQUEST: 'tool_request',
  TRANSCRIPT: 'transcript',
  AUDIO: 'audio',
  AUDIO_START: 'audio_start',
  AUDIO_END: 'audio_end',
  ERROR: 'error',
  DISCONNECTED: 'disconnected',
};

// Session types
export const SESSION_TYPES = {
  AUTHOR: 'author',
  REVIEWER: 'reviewer',
};

// Modes
export const MODES = {
  TEXT: 'text',
  PIPELINE: 'pipeline',
};
