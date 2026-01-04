/**
 * WebSocket Manager for PR Buddy Extension
 *
 * Manages WebSocket connection to PR Buddy backend.
 * Handles reconnection, message queuing, and event distribution.
 *
 * Note: In MV3 service workers, WebSocket connections can be interrupted
 * when the service worker goes idle. We handle reconnection gracefully.
 */

export class WebSocketManager {
  constructor() {
    this.ws = null;
    this.sessionId = null;
    this.messageQueue = [];
    this.eventListeners = new Map();
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.baseUrl = 'ws://localhost:8000';
  }

  /**
   * Set the base URL for WebSocket connections.
   * @param {string} url - Base URL (e.g., 'ws://localhost:8000')
   */
  setBaseUrl(url) {
    this.baseUrl = url.replace(/^http/, 'ws');
  }

  /**
   * Connect to WebSocket endpoint for a session.
   * @param {string} sessionId - Session ID to connect to.
   * @returns {Promise<void>}
   */
  async connect(sessionId) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      if (this.sessionId === sessionId) {
        console.log('[WS] Already connected to session:', sessionId);
        return;
      }
      this.disconnect();
    }

    this.sessionId = sessionId;
    const wsUrl = `${this.baseUrl}/ws/${sessionId}`;

    console.log('[WS] Connecting to:', wsUrl);

    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
          console.log('[WS] Connected to session:', sessionId);
          this.reconnectAttempts = 0;
          this.flushMessageQueue();
          this.emit('connected', { sessionId });
          resolve();
        };

        this.ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
          } catch (e) {
            console.error('[WS] Failed to parse message:', e);
          }
        };

        this.ws.onclose = (event) => {
          console.log('[WS] Connection closed:', event.code, event.reason);
          this.handleDisconnect(event);
        };

        this.ws.onerror = (error) => {
          console.error('[WS] Error:', error);
          reject(error);
        };
      } catch (error) {
        reject(error);
      }
    });
  }

  /**
   * Send message over WebSocket.
   * @param {Object} message - Message to send.
   */
  send(message) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      console.log('[WS] Sending:', message.type);
      this.ws.send(JSON.stringify(message));
    } else {
      console.log('[WS] Queueing message (not connected):', message.type);
      this.messageQueue.push(message);
      this.attemptReconnect();
    }
  }

  /**
   * Register event listener for WebSocket messages.
   * @param {string} eventType - Event type to listen for ('*' for all).
   * @param {Function} callback - Callback function.
   */
  on(eventType, callback) {
    if (!this.eventListeners.has(eventType)) {
      this.eventListeners.set(eventType, []);
    }
    this.eventListeners.get(eventType).push(callback);
  }

  /**
   * Remove event listener.
   * @param {string} eventType - Event type.
   * @param {Function} callback - Callback to remove.
   */
  off(eventType, callback) {
    const listeners = this.eventListeners.get(eventType);
    if (listeners) {
      const index = listeners.indexOf(callback);
      if (index > -1) {
        listeners.splice(index, 1);
      }
    }
  }

  /**
   * Emit event to listeners.
   * @param {string} eventType - Event type.
   * @param {Object} data - Event data.
   */
  emit(eventType, data) {
    const listeners = this.eventListeners.get(eventType) || [];
    const allListeners = this.eventListeners.get('*') || [];

    [...listeners, ...allListeners].forEach(callback => {
      try {
        callback({ type: eventType, ...data });
      } catch (e) {
        console.error('[WS] Listener error:', e);
      }
    });
  }

  /**
   * Handle incoming WebSocket message.
   * @param {Object} data - Parsed message data.
   */
  handleMessage(data) {
    console.log('[WS] Received:', data.type);

    const eventType = data.type;
    const listeners = this.eventListeners.get(eventType) || [];
    const allListeners = this.eventListeners.get('*') || [];

    [...listeners, ...allListeners].forEach(callback => {
      try {
        callback(data);
      } catch (e) {
        console.error('[WS] Listener error:', e);
      }
    });
  }

  /**
   * Handle disconnect and attempt reconnection.
   * @param {CloseEvent} event - WebSocket close event.
   */
  handleDisconnect(event) {
    const wasClean = event.wasClean;

    if (!wasClean && this.reconnectAttempts < this.maxReconnectAttempts && this.sessionId) {
      this.attemptReconnect();
    } else {
      this.emit('disconnected', {
        permanent: wasClean || this.reconnectAttempts >= this.maxReconnectAttempts,
        code: event.code,
        reason: event.reason,
      });
    }
  }

  /**
   * Attempt to reconnect after delay.
   */
  attemptReconnect() {
    if (!this.sessionId) return;

    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);

    console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

    setTimeout(() => {
      if (this.sessionId) {
        this.connect(this.sessionId).catch(error => {
          console.error('[WS] Reconnection failed:', error);
        });
      }
    }, delay);
  }

  /**
   * Flush queued messages after reconnection.
   */
  flushMessageQueue() {
    console.log(`[WS] Flushing ${this.messageQueue.length} queued messages`);
    while (this.messageQueue.length > 0) {
      const message = this.messageQueue.shift();
      this.send(message);
    }
  }

  /**
   * Check if connected.
   * @returns {boolean}
   */
  isConnected() {
    return this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  /**
   * Get current connection state.
   * @returns {string}
   */
  getState() {
    if (!this.ws) return 'disconnected';

    switch (this.ws.readyState) {
      case WebSocket.CONNECTING: return 'connecting';
      case WebSocket.OPEN: return 'connected';
      case WebSocket.CLOSING: return 'closing';
      case WebSocket.CLOSED: return 'disconnected';
      default: return 'unknown';
    }
  }

  /**
   * Disconnect WebSocket.
   */
  disconnect() {
    console.log('[WS] Disconnecting');
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.sessionId = null;
    this.reconnectAttempts = 0;
  }

  /**
   * Clear all listeners and disconnect.
   */
  destroy() {
    this.disconnect();
    this.eventListeners.clear();
    this.messageQueue = [];
  }
}

// Singleton instance
export const wsManager = new WebSocketManager();
