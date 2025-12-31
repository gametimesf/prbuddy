.PHONY: setup dev weaviate weaviate-stop test clean help

# Default target
help:
	@echo "PR Buddy - AI Review Companion"
	@echo ""
	@echo "Available targets:"
	@echo "  setup          - Install dependencies and set up environment"
	@echo "  dev            - Start development server (starts Weaviate if needed)"
	@echo "  weaviate       - Start Weaviate vector database"
	@echo "  weaviate-stop  - Stop Weaviate"
	@echo "  test           - Run tests"
	@echo "  clean          - Clean up generated files"

# Setup the development environment
setup:
	./setup.sh

# Start Weaviate vector database
weaviate:
	@echo "Starting Weaviate..."
	docker-compose up -d weaviate
	@echo "Waiting for Weaviate to be ready..."
	@until curl -sf http://localhost:8080/v1/.well-known/ready > /dev/null 2>&1; do \
		sleep 1; \
	done
	@echo "Weaviate is ready!"

# Stop Weaviate
weaviate-stop:
	docker-compose down

# Run development server
dev: weaviate
	uvicorn src.server.app:app --reload --port 8000

# Run tests
test:
	pytest tests/ -v

# Clean up
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov dist build *.egg-info

