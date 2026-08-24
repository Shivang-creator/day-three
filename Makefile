.PHONY: dev test demo quiet-diff diagram deploy

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
	@echo "TODO: deploy.sh (T-05)"
