def pytest_addoption(parser):
    parser.addoption(
        "--base-url",
        default=None,
        help="Test against a deployed instance (e.g., https://sheetgo-agent-xyz.run.app)",
    )
