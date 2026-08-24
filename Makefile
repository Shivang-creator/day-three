.PHONY: dev test demo quiet-diff diagram deploy deploy-dry

dev:
	@echo "Loading .env.local and starting uvicorn (reload) on :8080"
	uvicorn app.main:app --reload --port 8080

test:
	pytest -q

demo:
	@echo "TODO: tools/demo.py (T-24)"

quiet-diff:
	@echo "TODO: tools/quiet_diff.py (T-19)"

diagram:
	@echo "TODO: tools/diagram.py (T-25)"

deploy:
	@bash deploy.sh

deploy-dry:
	@bash deploy.sh --dry-run
