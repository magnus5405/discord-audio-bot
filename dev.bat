@echo off
REM Development commands for Discord Audio Bot (Windows)
REM Usage: dev.bat <command>

setlocal enabledelayedexpansion

if "%~1"=="" (
    set CMD=help
) else (
    set CMD=%~1
)

if "%CMD%"=="lint" (
    echo Running ruff linter...
    ruff check src\
    echo ✓ Ruff checks passed
    goto :EOF
)

if "%CMD%"=="format" (
    echo Formatting code with black...
    black src\ tests\
    echo Sorting imports with isort...
    isort src\ tests\
    echo ✓ Code formatted
    goto :EOF
)

if "%CMD%"=="type" (
    echo Running mypy type checker...
    mypy src\ --ignore-missing-imports --strict
    echo ✓ Type check complete
    goto :EOF
)

if "%CMD%"=="check" (
    echo Running all checks...
    black --check src\ tests\
    isort --check-only src\ tests\
    ruff check src\
    mypy src\ --ignore-missing-imports --strict
    echo ✓ All checks passed
    goto :EOF
)

if "%CMD%"=="test" (
    echo Running tests...
    pytest %~2 -v
    goto :EOF
)

if "%CMD%"=="test-cov" (
    echo Running tests with coverage...
    pytest --cov=src --cov-report=term-missing --cov-report=html
    goto :EOF
)

if "%CMD%"=="clean" (
    echo Cleaning up...
    for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
    del /s /q *.pyc 2>nul
    del /s /q .coverage 2>nul
    rmdir /s /q .pytest_cache 2>nul
    rmdir /s /q .mypy_cache 2>nul
    rmdir /s /q htmlcov 2>nul
    rmdir /s /q .ruff_cache 2>nul
    echo ✓ Cleaned up
    goto :EOF
)

if "%CMD%"=="install" (
    echo Installing dependencies...
    pip install -e ".[dev]"
    echo ✓ Dependencies installed
    goto :EOF
)

if "%CMD%"=="install-pre-commit" (
    echo Installing pre-commit hooks...
    pre-commit install
    echo ✓ Pre-commit hooks installed
    goto :EOF
)

if "%CMD%"=="pre-commit" (
    echo Running pre-commit on all files...
    pre-commit run --all-files
    goto :EOF
)

REM Default: help
echo Discord Audio Bot - Development Commands
echo.
echo Usage: dev.bat ^<command^>
echo.
echo Commands:
echo   lint              - Run ruff linter
echo   format            - Format code with black and sort imports
echo   type              - Run mypy type checker
echo   check             - Run all checks (format, lint, type)
echo   test [path]       - Run pytest on path or all tests
echo   test-cov          - Run tests with coverage report
echo   clean             - Remove cache and build files
echo   install           - Install dependencies
echo   install-pre-commit - Install pre-commit hooks
echo   pre-commit        - Run pre-commit on all files
echo   help              - Show this message
