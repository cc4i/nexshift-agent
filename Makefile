# NexShift Agent Makefile
# ========================
# Commands for development, testing, and deployment to GCP Agent Engine

.PHONY: run test run-ui build deploy deploy-check deploy-list deploy-test deploy-delete clean help

# =============================================================================
# Configuration - Override these with environment variables or command line
# =============================================================================
GOOGLE_CLOUD_PROJECT ?= multi-gke-ops
# GOOGLE_CLOUD_LOCATION ?= global
GOOGLE_CLOUD_LOCATION ?= us-central1
GOOGLE_GENAI_USE_VERTEXAI ?= TRUE

# Export these so subprocesses (like adk web) can see them
export GOOGLE_CLOUD_PROJECT
export GOOGLE_CLOUD_LOCATION
export GOOGLE_GENAI_USE_VERTEXAI

PROJECT_ID = $(GOOGLE_CLOUD_PROJECT)
LOCATION = $(GOOGLE_CLOUD_LOCATION)
STAGING_BUCKET ?= gs://$(PROJECT_ID)-nexshift-agent-staging
AGENT_NAME ?= nexshift-agent

# =============================================================================
# Development Commands
# =============================================================================

## Run the main script
run:
	uv run main.py

## Run the ADK web UI on port 8001
run-ui:
	@echo "Environment:"
	@echo "  GOOGLE_CLOUD_PROJECT: $(GOOGLE_CLOUD_PROJECT)"
	@echo "  GOOGLE_CLOUD_LOCATION: $(GOOGLE_CLOUD_LOCATION)"
	@echo "  GOOGLE_GENAI_USE_VERTEXAI: $(GOOGLE_GENAI_USE_VERTEXAI)"
	@echo ""
	@echo "Starting ADK web UI on port 8001..."
	uv run adk web . --port 8001

## Run tests (placeholder - runs smoke test)
test:
	uv run python -c "from agents.agent import root_agent; print(f'Agent loaded: {root_agent.name}, Tools: {len(root_agent.tools)}')"

## Validate Python syntax for all files
lint:
	uv run python -m py_compile agents/*.py tools/*.py

# =============================================================================
# GCP Agent Engine Deployment Commands
# =============================================================================

## Check deployment dependencies
deploy-check:
	@echo "🔍 Checking deployment dependencies..."
	uv run python scripts/deploy.py check
	@echo ""
	@echo "🔍 Checking GCP authentication..."
	@gcloud auth application-default print-access-token > /dev/null 2>&1 && echo "✅ GCP authenticated" || (echo "❌ Not authenticated. Run: gcloud auth application-default login" && exit 1)
	@echo ""
	@echo "🔍 Checking project configuration..."
	@echo "   PROJECT_ID: $(PROJECT_ID)"
	@echo "   LOCATION: $(LOCATION)"
	@echo "   STAGING_BUCKET: $(STAGING_BUCKET)"
	@echo "   AGENT_NAME: $(AGENT_NAME)"

## Create staging bucket if it doesn't exist
deploy-bucket:
	@echo "🪣 Creating staging bucket $(STAGING_BUCKET)..."
	@gsutil ls $(STAGING_BUCKET) 2>/dev/null || gsutil mb -p $(PROJECT_ID) -l $(LOCATION) $(STAGING_BUCKET)
	@echo "✅ Staging bucket ready"

## Deploy agent to GCP Agent Engine
deploy: deploy-check deploy-bucket
	@echo ""
	@echo "🚀 Deploying $(AGENT_NAME) to GCP Agent Engine..."
	uv run python scripts/deploy.py deploy \
		--project $(PROJECT_ID) \
		--location $(LOCATION) \
		--name $(AGENT_NAME)

## List deployed agents
deploy-list:
	@echo "📋 Listing deployed agents..."
	uv run python scripts/deploy.py list \
		--project $(PROJECT_ID) \
		--location $(LOCATION)

## Test deployed agent
deploy-test:
	@echo "🧪 Testing deployed agent..."
	uv run python scripts/deploy.py test \
		--project $(PROJECT_ID) \
		--location $(LOCATION)

## Delete deployed agent
deploy-delete:
	@echo "🗑️  Deleting deployed agent..."
	uv run python scripts/deploy.py delete \
		--project $(PROJECT_ID) \
		--location $(LOCATION)

# =============================================================================
# GCP Setup Commands
# =============================================================================

## Authenticate with GCP
gcp-auth:
	@echo "🔐 Authenticating with GCP..."
	gcloud auth application-default login

## Enable required GCP APIs
gcp-enable-apis:
	@echo "🔧 Enabling required GCP APIs..."
	gcloud services enable aiplatform.googleapis.com --project $(PROJECT_ID)
	gcloud services enable storage.googleapis.com --project $(PROJECT_ID)
	@echo "✅ APIs enabled"

## Full GCP setup (auth + APIs + bucket)
gcp-setup: gcp-auth gcp-enable-apis deploy-bucket
	@echo ""
	@echo "✅ GCP setup complete!"
	@echo "   You can now run: make deploy"

# =============================================================================
# Cleanup Commands
# =============================================================================

## Clean Python cache files
clean:
	rm -rf __pycache__ */__pycache__ */*/__pycache__
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete
	find . -name ".pytest_cache" -type d -exec rm -rf {} + 2>/dev/null || true

## Clean deployment artifacts
clean-deploy:
	rm -f deployment_info.json

## Full clean
clean-all: clean clean-deploy

# =============================================================================
# Help
# =============================================================================

## Show this help message
help:
	@echo "NexShift Agent - Makefile Commands"
	@echo "==================================="
	@echo ""
	@echo "Development:"
	@echo "  make run          - Run the main script"
	@echo "  make run-ui       - Run ADK web UI on port 8001"
	@echo "  make test         - Run smoke test"
	@echo "  make lint         - Validate Python syntax"
	@echo ""
	@echo "GCP Deployment:"
	@echo "  make deploy       - Deploy agent to GCP Agent Engine"
	@echo "  make deploy-check - Check deployment dependencies"
	@echo "  make deploy-list  - List deployed agents"
	@echo "  make deploy-test  - Test deployed agent"
	@echo "  make deploy-delete- Delete deployed agent"
	@echo ""
	@echo "GCP Setup:"
	@echo "  make gcp-auth     - Authenticate with GCP"
	@echo "  make gcp-enable-apis - Enable required APIs"
	@echo "  make gcp-setup    - Full GCP setup (auth + APIs + bucket)"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean        - Clean Python cache files"
	@echo "  make clean-deploy - Clean deployment artifacts"
	@echo "  make clean-all    - Full clean"
	@echo ""
	@echo "Configuration (override with env vars or command line):"
	@echo "  PROJECT_ID=$(PROJECT_ID)"
	@echo "  LOCATION=$(LOCATION)"
	@echo "  STAGING_BUCKET=$(STAGING_BUCKET)"
	@echo "  AGENT_NAME=$(AGENT_NAME)"
	@echo ""
	@echo "Example:"
	@echo "  make deploy PROJECT_ID=my-project STAGING_BUCKET=gs://my-bucket"
