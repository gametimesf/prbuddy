#!/bin/bash
# Setup script for PR Buddy

set -e

echo "PR Buddy Setup"
echo "=============="

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
REQUIRED_VERSION="3.10"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "Error: Python $REQUIRED_VERSION or higher is required (found $PYTHON_VERSION)"
    exit 1
fi
echo "✓ Python $PYTHON_VERSION"

# Check for uv (preferred) or pip
if command -v uv &> /dev/null; then
    echo "✓ uv found, using uv for package management"
    INSTALLER="uv"
else
    echo "✓ Using pip for package management"
    INSTALLER="pip"
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
if [ "$INSTALLER" = "uv" ]; then
    uv pip install -e ".[dev]"
else
    pip install -e ".[dev]"
fi

# Check for .env file
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cat > .env << 'EOF'
# OpenAI API Key (required)
OPENAI_API_KEY=your-openai-api-key-here

# Optional: GitHub token for higher rate limits
# GITHUB_TOKEN=your-github-token

# Optional: Verbose logging (0=quiet, 1=verbose, 2=debug)
VERBOSE=0
EOF
    echo "⚠ Please edit .env and add your OPENAI_API_KEY"
fi

# Check Docker
if command -v docker &> /dev/null; then
    echo "✓ Docker found"
else
    echo "⚠ Docker not found - required for Weaviate"
fi

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env and add your OPENAI_API_KEY"
echo "  2. Run 'make weaviate' to start the vector database"
echo "  3. Run 'make dev' to start the development server"

