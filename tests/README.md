# API Endpoint Tests

This directory contains automated tests for all API endpoints in the chatwise-be project.

## Structure

The test suite follows the structure of the API:

- `tests/api/routes/test_agent.py` - Tests for agent-related endpoints
- `tests/api/routes/test_chat.py` - Tests for chat-related endpoints
- `tests/api/routes/test_file.py` - Tests for file upload/management endpoints
- `tests/api/routes/test_scrape.py` - Tests for web scraping endpoints

## Test Environment

Tests use a dedicated test environment with separate databases:
- ChromaDB: `./chromadb_data_test`
- SQLite: `./db_test/kb_metadata_test.sqlite`

These paths are configured in the `.env.test` file, which is automatically loaded during test execution.

## Running Tests

### Run all tests

```bash
pytest
```

### Run tests for a specific module

```bash
# Test specific file
pytest tests/api/routes/test_agent.py

# Test specific class
pytest tests/api/routes/test_agent.py::TestAgentEndpoints

# Test specific function
pytest tests/api/routes/test_agent.py::TestAgentEndpoints::test_create_agent
```

### Run with verbose output

```bash
pytest -v
```

### Generate test coverage report

```bash
pytest --cov=app
```

## Writing New Tests

When writing new tests, follow these guidelines:

1. Place tests in the appropriate module based on the endpoint being tested
2. Use fixtures for test data and common setup
3. Use the `client` fixture for making requests to the API
4. When testing endpoints that require created resources, ensure cleanup happens after the test
5. Isolate tests to prevent interference between them

## Notes for Test Maintenance

- The test KB IDs are generated dynamically during test runs
- Some tests depend on the results of previous test functions, so the order within classes matters
- Some tests involve background tasks (e.g., scraping) and include small time delays to account for processing 