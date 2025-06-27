import pytest

from taskcond.core.manager import TaskManager


@pytest.fixture(autouse=True)
def fresh_manager() -> None:
    """
    Ensures that each test gets a fresh, empty TaskManager instance by
    clearing the singleton's state before each test.
    """
    if hasattr(TaskManager, "_instance"):
        delattr(TaskManager, "_instance")
