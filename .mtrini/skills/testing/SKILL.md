# Testing

Test behavior, not implementation.
- Python: pytest with tmp_path/monkeypatch fixtures; async tests with pytest-asyncio (auto mode here).
- Frontend: vitest + testing-library; assert what the user sees, mock the network edge.
- Every new tool/provider/endpoint gets a test; every bugfix gets a regression test first.
- Keep tests hermetic: no paid APIs, no hardcoded ports, no real model downloads in CI.
- Name tests after the guarantee: test_path_traversal_blocked, not test_security_2.
Run the focused file first for speed, then the whole suite before finishing.
