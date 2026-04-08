# PR Buddy

An AI-powered review companion for pull requests. Authors train agents with context about their PR, and reviewers can then ask questions — getting answers grounded in author knowledge, code diffs, and team context.

## How It Works

```mermaid
sequenceDiagram
    participant Author
    participant PRBuddy as PR Buddy
    participant Weaviate as Knowledge Base<br/>(Weaviate)
    participant GitHub
    participant Unblocked

    Note over PRBuddy,Weaviate: Session Creation
    PRBuddy->>GitHub: Fetch diff, description, comments
    GitHub-->>PRBuddy: PR content
    PRBuddy->>Weaviate: Auto-index diff chunks,<br/>description, comments

    Note over Author,Weaviate: Author Training
    Author->>PRBuddy: "Edgar likes this approach"
    PRBuddy->>Weaviate: Index author_explanation<br/>(preserves entity names)
    PRBuddy-->>Author: Got it - Edgar approves<br/>the explicit access approach.

    Note over Author,Unblocked: Research (when needed)
    Author->>PRBuddy: "What did the team discuss?"
    PRBuddy->>Unblocked: Search team context,<br/>Slack, historical decisions
    Unblocked-->>PRBuddy: Relevant discussions
    PRBuddy->>Weaviate: Index findings
    PRBuddy-->>Author: Team discussed via Envoy...
```

```mermaid
sequenceDiagram
    participant Reviewer
    participant PRBuddy as PR Buddy
    participant Weaviate as Knowledge Base<br/>(Weaviate)

    Note over Reviewer,Weaviate: Reviewer Q&A (auto-injection)
    Reviewer->>PRBuddy: "Is Edgar ok with this?"
    PRBuddy->>Weaviate: 3 parallel queries:<br/>hybrid + BM25 + vector
    Weaviate-->>PRBuddy: Matching docs<br/>(author explanations, diff, etc.)
    Note over PRBuddy: Deduplicate, rank,<br/>inject as system context
    PRBuddy-->>Reviewer: Edgar reviewed and approves.<br/>He likes the explicit single-service access.
```

## Architecture

```mermaid
graph TB
    subgraph Frontend
        WEB[Web UI<br/>Voice + Text]
        EXT[Chrome Extension<br/>Side Panel + Diff Selection]
    end

    subgraph Server["FastAPI Server"]
        WS[WebSocket Handler]
        TEXT[Text Session]
        PIPE[Pipeline Session<br/>STT + Agent + TTS]
        CI[Context Injection<br/>Multi-query RAG]
    end

    subgraph Agents["Agent System (YAML-configured)"]
        AT[AuthorTraining]
        RQ[ReviewerQA]
        RE[Research]
        AT <-->|handoff| RE
        RQ <-->|handoff| RE
    end

    subgraph Storage
        WV[(Weaviate<br/>Vector DB)]
    end

    subgraph External
        GH[GitHub API]
        UB[Unblocked MCP<br/>Team Knowledge]
    end

    WEB --> WS
    EXT --> WS
    WS --> TEXT
    WS --> PIPE
    TEXT --> CI
    CI --> WV
    TEXT --> Agents
    PIPE --> Agents
    Agents --> WV
    RE --> GH
    RE --> UB
```

## Key Features

- **Auto-indexed PR context** — Diff, description, and comments are fetched from GitHub and indexed into Weaviate on session creation. Agents start with full context immediately.
- **Auto-context injection** — Before each reviewer question, 3 parallel RAG queries (hybrid, BM25, vector) surface relevant author knowledge automatically. The agent doesn't need to decide to search.
- **Entity-aware indexing** — Author explanations preserve people, team, and system names for reliable keyword matching (e.g., "Edgar" stays "Edgar", not "a stakeholder").
- **Voice + Text modes** — Text chat or voice (Whisper STT + Polly/OpenAI TTS).
- **Diff selection** — Chrome extension lets reviewers highlight code and ask questions with that context.
- **Research via Unblocked MCP** — Agents can search Slack, Jira, historical PRs, and team discussions.

## Quick Start

```bash
# Setup
make setup

# Edit .env and add your OPENAI_API_KEY

# Start Weaviate + dev server
make dev
```

Then open http://localhost:8000 in your browser.

### Chrome Extension

Load the extension for the side panel experience on GitHub PRs:

1. Go to `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** and select the `prbuddy-extension/` directory

### Voice Mode Requirements

For voice modes (Pipeline), you need:
- **ffmpeg** — `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Linux)
- **OPENAI_API_KEY** — For Whisper STT
- **AWS credentials** or **ELEVENLABS_API_KEY** — For TTS

## Session Modes

| Mode | Description | Latency |
|------|-------------|---------|
| **Text** | Chat-based Q&A | Instant |
| **Pipeline** | Whisper STT + Agent + TTS | ~2-3s |

## Configuration

Agent behaviors are configured via YAML files in `config/agents/`:

| Directory | Agents | Purpose |
|-----------|--------|---------|
| `common/` | Research | Context gathering from GitHub + Unblocked |
| `author/` | AuthorTraining, AuthorEngagement | Author interview and knowledge capture |
| `reviewer/` | ReviewerQA | Reviewer Q&A with citations |

## Development

```bash
make setup    # Install dependencies
make dev      # Start Weaviate + server (hot reload)
make test     # Run unit tests (81 tests)
make eval     # Run evals (requires Weaviate + OPENAI_API_KEY)
make clean    # Clean up generated files
```

## Evals

The `evals/` directory contains end-to-end scenarios that verify author-to-reviewer knowledge sharing:

| Scenario | Tests |
|----------|-------|
| `edgar_approval` | Author says "Edgar likes this" — reviewer can find it with 5 phrasings |
| `technical_decision` | Author explains tradeoff — reviewer finds the reasoning |
| `indirect_reference` | Author provides context — reviewer finds it with different wording |

```bash
make eval  # Requires Weaviate running + OPENAI_API_KEY
```

## License

MIT
