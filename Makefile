# -- Variables -----------------------------------------------------------------

TEST_DIRECTORY = test

# -- Rules ---------------------------------------------------------------------

.PHONY: check
check:
	poetry run mypy .
	poetry run flake8 $(TEST_DIRECTORY)