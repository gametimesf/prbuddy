# PR Buddy

An AI-powered review companion for pull requests that enables authors to train agents for reviewer Q&A.

## Overview

PR Buddy acts as a stand-in for the PR author during code review. Authors train the agent with context about their PR, and reviewers can then ask questions without requiring the author to be present.

### Features

- **Author Training**: Authors explain their PR's intent, tradeoffs, and context
- **Reviewer Q&A**: Reviewers ask questions and get answers with source citations
- **Voice & Text Modes**: Interact via text chat or voice (Whisper + TTS)
- **RAG-Powered**: Uses Weaviate for semantic search over PR context
- **GitHub Integration**: Fetches PR diffs, comments, and linked issues via MCP

## Quick Start

```bash
# Setup
make setup

# Edit .env and add your OPENAI_API_KEY

# Start Weaviate
make weaviate

# Start development server
make dev
```

Then open http://localhost:8000 in your browser.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│   Web App UI    │────▶│  FastAPI Server │
│  (Voice/Text)   │     │   (WebSocket)   │
└─────────────────┘     └────────┬────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Text Mode      │     │ Pipeline Mode   │     │ Realtime Mode   │
│  (Agent only)   │     │ (STT+Agent+TTS) │     │ (OpenAI RT API) │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │  Agent System   │
                        │  (YAML configs) │
                        └────────┬────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
              ▼                  ▼                  ▼
     ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
     │   Weaviate RAG  │ │   GitHub MCP    │ │    Jira MCP     │
     │  (Vector Store) │ │  (PR Context)   │ │  (Linked Issues)│
     └─────────────────┘ └─────────────────┘ └─────────────────┘
```

## Session Modes

| Mode | Description | Latency |
|------|-------------|---------|
| **Text** | Chat-based Q&A | Instant |
| **Pipeline** | Whisper STT + Agent + Polly/ElevenLabs TTS | ~2-3s |
| **Realtime** | OpenAI Realtime API | ~500ms |

### Voice Mode Requirements

For voice modes (Pipeline and Realtime), you need:
- **ffmpeg**: For audio format conversion (browser sends WebM, pipeline expects PCM)
  ```bash
  # macOS
  brew install ffmpeg
  
  # Ubuntu/Debian
  sudo apt install ffmpeg
  ```
- **OPENAI_API_KEY**: For Whisper STT
- **AWS credentials** or **ELEVENLABS_API_KEY**: For TTS

## Development

```bash
# Install dev dependencies
make setup

# Run tests
make test

# Start server with hot reload
make dev
```

## Configuration

Agent behaviors are configured via YAML files in `config/agents/`:

- `research.yaml` - Context gathering from GitHub/Jira
- `author_training.yaml` - Author interview flow
- `reviewer_qa.yaml` - Reviewer Q&A with citations

## License

MIT

