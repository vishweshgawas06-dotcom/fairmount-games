# CI Workflows

`python-tests.yml` installs the Python project on Python 3.12 and runs the unittest suite and Ruff on pull requests and pushes to `main`. It was added with the P01 API foundation. A workflow definition alone does not prove the checks pass: record actual GitHub run evidence in the active task before marking that task complete. No frontend, database, or gameplay CI is configured yet.
