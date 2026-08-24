.PHONY: dev test demo quiet-diff diagram deploy deploy-dry

dev:
	@echo "Loading .env.local and starting uvicorn (reload) on :8080"
	uvicorn app.main:app --reload --port 8080

test:
	pytest -q
	@echo "TEST COUNT: $$(pytest --collect-only -q | tail -1)"

demo:
	python -m tools.demo

quiet-diff:
	python -m tools.quiet_diff

diagram:
	python tools/diagram.py

deploy:
	@bash deploy.sh

deploy-dry:
	@bash deploy.sh --dry-run
