# PR Buddy Chrome Extension

AI-powered PR review assistant that integrates directly with GitHub pull request pages.

## Features

- **Author Mode**: Train the AI about your PR changes and decisions
- **Reviewer Mode**: Ask questions about the PR and get AI-powered answers
- **Auto-detect PR Context**: Automatically detects the PR when you're on a GitHub PR page
- **Selection Context**: Highlight code and ask "What is this?" - the agent can see your selection

## Installation

### Development Mode

1. Open Chrome and go to `chrome://extensions/`
2. Enable "Developer mode" (toggle in top-right)
3. Click "Load unpacked"
4. Select the `prbuddy-extension` folder

### Requirements

- PR Buddy backend running at `http://localhost:8000`
- Chrome browser (Manifest V3)

## Usage

1. Navigate to a GitHub pull request page (e.g., `github.com/owner/repo/pull/123`)
2. Click the PR Buddy extension icon in the Chrome toolbar
3. Select a mode:
   - **Author**: If you're the PR author, use this to explain your changes
   - **Reviewer**: If you're reviewing, use this to ask questions
4. Start chatting with the AI assistant

### Selection Feature

You can highlight code on the PR page and ask questions about it:

1. Select/highlight any text on the PR page (code, comments, description)
2. In the chat, ask something like "What is this?" or "Explain this code"
3. The agent will automatically retrieve your selection and include it in its response

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Content Script │────▶│  Service Worker │────▶│  PR Buddy API   │
│  (GitHub page)  │     │  (Background)   │     │  (localhost)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │
        │                       │
        ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│  PR Detection   │     │    Popup UI     │
│  Selection      │     │    Chat         │
└─────────────────┘     └─────────────────┘
```

- **Content Script**: Runs on GitHub PR pages, detects PR context and captures text selection
- **Service Worker**: Manages WebSocket connection to backend, routes messages
- **Popup UI**: User interface for mode selection and chat

## Files

```
prbuddy-extension/
├── manifest.json           # Chrome extension manifest (MV3)
├── icons/                  # Extension icons
├── src/
│   ├── background/
│   │   ├── service-worker.js   # Background service worker
│   │   └── ws-manager.js       # WebSocket connection manager
│   ├── content/
│   │   ├── content-script.js   # Main content script
│   │   ├── pr-detector.js      # PR context detection
│   │   └── selection-handler.js # Text selection capture
│   ├── popup/
│   │   ├── popup.html          # Popup UI
│   │   ├── popup.css           # Styles
│   │   └── popup.js            # Popup logic
│   └── shared/
│       ├── constants.js        # Shared constants
│       └── storage.js          # Chrome storage wrapper
└── styles/
    └── content.css             # Injected styles
```

## Development

### Debugging

1. Open `chrome://extensions/`
2. Click "Inspect views: service worker" to debug the background script
3. Open DevTools on a GitHub PR page to debug the content script
4. Right-click the extension icon and select "Inspect popup" to debug the popup

### Reloading

After making changes:
1. Go to `chrome://extensions/`
2. Click the refresh icon on the PR Buddy extension card
3. Reload any GitHub PR pages to get the updated content script

## Troubleshooting

### "Not on a PR Page"

Make sure you're on a GitHub pull request page with a URL like:
`https://github.com/owner/repo/pull/123`

### "Connection Error"

1. Check that PR Buddy backend is running at `http://localhost:8000`
2. Check the browser console for error details
3. Try the `/health` endpoint: `http://localhost:8000/health`

### Selection Not Working

1. Make sure you have text selected on the page
2. The selection must be within the PR page content (diff, comments, description)
3. Check the content script console for errors
