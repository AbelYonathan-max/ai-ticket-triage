# Common tasks. Run `make help` for the list.
PY ?= python

.PHONY: help install data train test test-all lint typecheck security run docker clean

help:
	@grep -E '^[a-z-]+:.*## ' Makefile | sed 's/:.*## /\t/'

install: ## Install the app with development tools
	$(PY) -m pip install -e ".[dev]"

data: ## Generate the synthetic training tickets
	$(PY) -m triage.data.synthetic --out data/synthetic/train.csv

train: data ## Train and evaluate the model, refresh the model card
	$(PY) -m triage.ml.train --out models --docs docs

test: ## Unit and API tests (SQLite)
	$(PY) -m pytest -m "not mssql and not quality" --cov --cov-report=term-missing

test-all: train ## Everything, including the model quality gate
	$(PY) -m pytest -m "not mssql"

lint: ## Ruff lint and format check
	ruff check src tests
	ruff format --check src tests

typecheck: ## mypy
	mypy

security: ## Bandit and pip-audit
	bandit -q -c pyproject.toml -r src
	pip-audit --skip-editable

run: ## Run locally on SQLite with the stub AI assistant
	TRIAGE_DATABASE_URL=sqlite:///./triage.db TRIAGE_AUTO_MIGRATE=true TRIAGE_SEED_DEMO=true \
	TRIAGE_LLM_PROVIDER=stub uvicorn --factory triage.api.app:create_app --reload

docker: ## Build the container image
	docker build -t ai-ticket-triage:local .

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info triage.db
