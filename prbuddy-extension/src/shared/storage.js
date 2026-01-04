/**
 * Chrome storage wrapper for PR Buddy extension.
 */

/**
 * Get stored session data.
 * @returns {Promise<Object|null>} Session data or null if not found.
 */
export async function getSession() {
  const { session } = await chrome.storage.local.get('session');
  return session || null;
}

/**
 * Store session data.
 * @param {Object} session - Session data to store.
 */
export async function setSession(session) {
  await chrome.storage.local.set({ session });
}

/**
 * Clear stored session.
 */
export async function clearSession() {
  await chrome.storage.local.remove('session');
}

/**
 * Get extension settings.
 * @returns {Promise<Object>} Settings object.
 */
export async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  return settings || {
    backendUrl: 'http://localhost:8000',
    defaultMode: 'text',
  };
}

/**
 * Update extension settings.
 * @param {Object} updates - Settings to update.
 */
export async function updateSettings(updates) {
  const current = await getSettings();
  await chrome.storage.local.set({
    settings: { ...current, ...updates },
  });
}
