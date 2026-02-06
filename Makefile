.PHONY: help install dev lint format test test-unit test-integration coverage typecheck clean docker-build docker-run run dry-run

# Colors for terminal output
BLUE := \033[34m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m

help: ## Show this help message
	@echo "$(BLUE)Arbitrage Engine$(RESET) - Development Commands"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "$(GREEN)%-20s$(RESET) %s\n", $$1, $$2}'

# =============================================================================
# Installation
# =============================================================================

install: ## Install dependencies
	poetry install --no-dev

dev: ## Install dev dependencies
	poetry install
	poetry run pre-commit install

# =============================================================================
# Code Quality
# =============================================================================

lint: ## Run linters (ruff)
	poetry run ruff check src tests

format: ## Format code (ruff)
	poetry run ruff format src tests
	poetry run ruff check --fix src tests

typecheck: ## Run type checker (mypy)
	poetry run mypy src

check: lint typecheck ## Run all checks (lint + typecheck)

# =============================================================================
# Testing
# =============================================================================

test: ## Run all tests
	poetry run pytest tests -v

test-unit: ## Run unit tests only
	poetry run pytest tests/unit -v

test-integration: ## Run integration tests only
	poetry run pytest tests/integration -v

coverage: ## Run tests with coverage report
	poetry run pytest tests -v --cov=src/arbitrage --cov-report=html --cov-report=term-missing
	@echo "$(GREEN)Coverage report generated in htmlcov/$(RESET)"

# =============================================================================
# Running
# =============================================================================

run: ## Run the arbitrage engine
	poetry run python -m arbitrage

dry-run: ## Run in dry-run mode
	DRY_RUN=true poetry run python -m arbitrage

testnet: ## Run against testnet
	USE_TESTNET=true DRY_RUN=true poetry run python -m arbitrage

demo: ## Run the demo dashboard (no API keys needed!)
	@echo "$(GREEN)Starting demo dashboard...$(RESET)"
	@echo "$(BLUE)Open http://localhost:8000 in your browser$(RESET)"
	poetry run python -m arbitrage.dashboard.server

# =============================================================================
# Docker
# =============================================================================

docker-build: ## Build Docker image
	docker build -t arbitrage-engine:latest -f docker/Dockerfile .

docker-run: ## Run Docker container
	docker run --rm -it --env-file .env arbitrage-engine:latest

docker-compose-up: ## Start with docker-compose
	docker-compose -f docker/docker-compose.yml up -d

docker-compose-down: ## Stop docker-compose services
	docker-compose -f docker/docker-compose.yml down

# =============================================================================
# Development Utilities
# =============================================================================

clean: ## Clean build artifacts
	rm -rf build dist *.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "$(GREEN)Cleaned!$(RESET)"

shell: ## Start Python shell with project context
	poetry run python

discover: ## Run triangle discovery script
	poetry run python scripts/discover_triangles.py

benchmark: ## Run latency benchmark
	poetry run python scripts/benchmark.py

# =============================================================================
# Git Helpers
# =============================================================================

pre-commit: ## Run pre-commit hooks
	poetry run pre-commit run --all-files

# =============================================================================
# Documentation
# =============================================================================

docs: ## Generate documentation (if using sphinx/mkdocs)
	@echo "$(YELLOW)Documentation generation not configured$(RESET)"
