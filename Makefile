# -- Variables -----------------------------------------------------------------

MODULE = icoapi
TEST_DIRECTORY = test

# -- Rules ---------------------------------------------------------------------

all: check test

.PHONY: check
check:
	poetry run mypy .
	poetry run flake8 $(TEST_DIRECTORY)

.PHONY: test
test:
	poetry run pytest

.PHONY: run
run: check
	poetry run python3 $(MODULE)/api.py