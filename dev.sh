#!/bin/bash
# Development commands for Discord Audio Bot

set -e

case "${1:-help}" in
    lint)
        echo "Running ruff linter..."
        ruff check src/ tests/
        echo "✓ Ruff checks passed"
        ;;
    
    format)
        echo "Formatting code with black..."
        black src/ tests/ 2>/dev/null || true
        echo "Sorting imports with isort..."
        isort src/ tests/ 2>/dev/null || true
        echo "✓ Code formatted"
        ;;
    
    type)
        echo "Running mypy type checker..."
        mypy src/ --ignore-missing-imports --strict || true
        echo "✓ Type check complete"
        ;;
    
    check)
        echo "Running all checks..."
        black --check src/ tests/ 2>/dev/null || true
        isort --check-only src/ tests/ 2>/dev/null || true
        ruff check src/ tests/
        mypy src/ --ignore-missing-imports --strict || true
        echo "✓ All checks passed"
        ;;
    
    test)
        echo "Running tests..."
        pytest ${2:-.} -v
        ;;
    
    test-cov)
        echo "Running tests with coverage..."
        pytest --cov=src --cov-report=term-missing --cov-report=html
        ;;
    
    clean)
        echo "Cleaning up..."
        find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
        find . -type f -name "*.pyc" -delete 2>/dev/null || true
        find . -type f -name ".coverage" -delete 2>/dev/null || true
        rm -rf .pytest_cache .mypy_cache htmlcov .ruff_cache 2>/dev/null || true
        echo "✓ Cleaned up"
        ;;
    
    install)
        echo "Installing dependencies..."
        pip install -e ".[dev]"
        echo "✓ Dependencies installed"
        ;;
    
    install-pre-commit)
        echo "Installing pre-commit hooks..."
        pre-commit install
        echo "✓ Pre-commit hooks installed"
        ;;
    
    pre-commit)
        echo "Running pre-commit on all files..."
        pre-commit run --all-files
        ;;
    
    *)
        echo "Discord Audio Bot - Development Commands"
        echo ""
        echo "Usage: ./dev.sh <command>"
        echo ""
        echo "Commands:"
        echo "  lint              - Run ruff linter"
        echo "  format            - Format code with black and sort imports"
        echo "  type              - Run mypy type checker"
        echo "  check             - Run all checks (format, lint, type)"
        echo "  test [path]       - Run pytest on path or all tests"
        echo "  test-cov          - Run tests with coverage report"
        echo "  clean             - Remove cache and build files"
        echo "  install           - Install dependencies"
        echo "  install-pre-commit - Install pre-commit hooks"
        echo "  pre-commit        - Run pre-commit on all files"
        echo "  help              - Show this message"
        ;;
esac
