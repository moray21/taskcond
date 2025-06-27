import pytest

from taskcond.core.manager import TaskManager, register
from taskcond.core.task import Task


class TestTaskManager:
    """Unit tests for the TaskManager class."""

    def test_singleton_behavior(self) -> None:
        """
        Tests that TaskManager is a singleton, i.e., it always returns the same instance.
        """
        manager1 = TaskManager()
        manager2 = TaskManager()
        assert manager1 == manager2

    def test_register_task_success(self) -> None:
        """
        Tests successful registration of a new task.
        """
        manager = TaskManager()
        task_a = Task(name="A")
        manager.register(task_a)

        assert "A" in manager.task_names
        assert manager.get_task("A") == task_a

    def test_register_duplicate_task_fails(self) -> None:
        """
        Tests that registering a task with a duplicate name raises a ValueError.
        """
        manager = TaskManager()
        task_a1 = Task(name="A")
        task_a2 = Task(name="A")

        manager.register(task_a1)
        with pytest.raises(ValueError, match="Task with name 'A' already registered."):
            manager.register(task_a2)

    def test_get_task_success(self) -> None:
        """
        Tests retrieving a registered task by its name.
        """
        manager = TaskManager()
        task = Task(name="my-task")
        manager.register(task)
        retrieved_task = manager.get_task("my-task")
        assert retrieved_task == task

    def test_get_unknown_task_fails(self) -> None:
        """
        Tests that trying to retrieve an unregistered task raises a ValueError.
        """
        manager = TaskManager()
        with pytest.raises(ValueError, match="Task 'unknown-task' is not defined."):
            manager.get_task("unknown-task")

    def test_manager_properties(self) -> None:
        """
        Tests the correctness of `task_dicts`, `tasks`, and `task_names` properties.
        """
        manager = TaskManager()
        task_a = Task(name="A")
        task_b = Task(name="B")
        manager.register(task_a)
        manager.register(task_b)

        assert sorted(manager.task_names) == ["A", "B"]
        assert len(manager.tasks) == 2
        assert task_a in manager.tasks
        assert task_b in manager.tasks
        assert manager.task_dicts["A"] == task_a
        assert manager.task_dicts["B"] == task_b

        # Test that task_dicts is read-only
        with pytest.raises(TypeError):
            manager.task_dicts["C"] = Task(name="C")  # type: ignore

    def test_validate_cycles_no_cycle(self) -> None:
        """
        Tests that validate_cycles() passes for a valid Directed Acyclic Graph (DAG).
        """
        manager = TaskManager()
        # A -> B, A -> C, B -> D, C -> D
        manager.register(Task(name="A", depends=("B", "C")))
        manager.register(Task(name="B", depends=("D",)))
        manager.register(Task(name="C", depends=("D",)))
        manager.register(Task(name="D"))

        # Should not raise
        manager.validate_cycles()

    def test_validate_cycles_simple_direct_cycle(self) -> None:
        """
        Tests that validate_cycles() detects a simple direct cycle (A -> B -> A).
        """
        manager = TaskManager()
        manager.register(Task(name="A", depends=("B",)))
        manager.register(Task(name="B", depends=("A",)))

        with pytest.raises(ValueError, match="Cyclic dependency detected: A -> B -> A"):
            manager.validate_cycles()

    def test_validate_cycles_long_cycle(self) -> None:
        """
        Tests that validate_cycles() detects a longer cycle (A -> B -> C -> A).
        """
        manager = TaskManager()
        manager.register(Task(name="A", depends=("B",)))
        manager.register(Task(name="B", depends=("C",)))
        manager.register(Task(name="C", depends=("A",)))

        with pytest.raises(
            ValueError, match="Cyclic dependency detected: A -> B -> C -> A"
        ):
            manager.validate_cycles()

    def test_validate_cycles_unknown_dependency(self) -> None:
        """
        Tests that validate_cycles() fails if a task depends on an unregistered task.
        """
        manager = TaskManager()
        manager.register(Task(name="A", depends=("UNKNOWN",)))

        with pytest.raises(
            ValueError, match="Task 'A' depends on unknown task 'UNKNOWN'"
        ):
            manager.validate_cycles()


def test_register() -> None:
    """
    Tests the global `register` convenience function.
    """
    task_a = Task(name="A")
    register(task_a)

    manager = TaskManager()
    assert "A" in manager.task_names
    assert manager.get_task("A") is task_a
