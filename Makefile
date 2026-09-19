# Adhikar. `make help` lists targets.
#
# Everything here runs with no API key: the offline engine is a real
# implementation, so a fresh clone can lint, type-check and test immediately.

VENV := .venv
PY := $(VENV)/bin/python
UV := uv

.DEFAULT_GOAL := help
.PHONY: help install fixtures test cover lint format typecheck security check demo serve clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Create the virtualenv and install everything
	$(UV) python install 3.12
	$(UV) venv --python 3.12
	$(UV) pip install -e ".[dev,anthropic]"
	@echo "Done. Run 'make demo' to see the injection demonstration."

fixtures:  ## Generate the adversarial PDF fixtures
	$(PY) scripts/make_fixtures.py

test:  ## Run the test suite
	$(PY) -m pytest -q

cover:  ## Run tests with a coverage report
	$(PY) -m pytest --cov --cov-report=term-missing --cov-report=html
	@echo "HTML report: htmlcov/index.html"

lint:  ## Lint and check formatting
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

format:  ## Apply formatting and safe lint fixes
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

typecheck:  ## Type-check in strict mode
	$(VENV)/bin/mypy

security:  ## Static analysis, dependency audit and the adversarial gate
	$(VENV)/bin/bandit -c pyproject.toml -r src/ -ll
	$(VENV)/bin/pip-audit --skip-editable
	$(PY) scripts/verify_defences.py

check: lint typecheck test security  ## Everything CI runs

demo:  ## Show a poisoned contract against both pipelines
	$(PY) scripts/demo_injection.py

serve:  ## Run the web application at http://127.0.0.1:8000
	$(PY) -m uvicorn adhikar.api.app:create_app --factory --reload --port 8000

clean:  ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
