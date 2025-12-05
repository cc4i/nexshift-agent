.PHONY: run test deploy clean

run:
	uv run main.py

test:
	# Placeholder for unit tests. For now, running the main script as a smoke test.
	uv run main.py

run-ui:
	uv run adk web . --port 8001

deploy:
	# Placeholder for Agent Engine deployment.
	# In a real scenario, this would be:
	# gcloud run deploy nurse-rostering-agent --source .
	@echo "Deploying to Agent Engine..."
	@echo "Deployment complete (mock)."

clean:
	rm -rf __pycache__
	find . -name "*.pyc" -delete
