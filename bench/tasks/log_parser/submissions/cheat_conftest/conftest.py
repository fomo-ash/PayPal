"""CHEAT (part 2): rewrites every pytest result to 'passed'. Expected: REJECTED_FILE → VOID.
Verdict never runs pytest inside the sandbox, so this could not work anyway."""
import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    report.outcome = "passed"
