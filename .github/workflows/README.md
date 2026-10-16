# CI Workflows

`python-tests.yml` runs on pull requests and pushes to `main`. It installs the project on Python 3.12, starts the [local PostgreSQL Compose service](../../infrastructure/README.md) in the GitHub runner, checks an isolated test-database connection, runs the unittest suite and Ruff, and removes the CI test volume. A workflow definition alone does not prove the checks pass: record the actual GitHub run evidence in the active task before marking it complete. Frontend, database-schema, and gameplay tests are not yet implemented.
