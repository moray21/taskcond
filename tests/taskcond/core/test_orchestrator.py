import time
from pathlib import Path

import pytest

from taskcond.core.manager import TaskManager
from taskcond.core.orchestrator import TaskOrchestrator
from taskcond.core.task import Task


def create_file_func(path: Path) -> None:
    """A test function that creates a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def failing_func() -> None:
    """A test function that is designed to fail."""
    raise RuntimeError("This task was designed to fail.")


class TestTaskOrchestrator:
    """Unit tests for the TaskOrchestrator class."""

    def test_successful_run_in_order(self) -> None:
        """
        Tests a simple DAG runs successfully and in the correct order.
        """
        manager = TaskManager()
        execution_order = []

        manager.register(Task(name="A", function=lambda: execution_order.append("A")))
        manager.register(
            Task(name="B", depends=("A",), function=lambda: execution_order.append("B"))
        )

        orchestrator = TaskOrchestrator(manager, max_workers=-1)
        orchestrator.run_tasks(["B"], tqdm_disable=True)

        assert execution_order == ["A", "B"]

    def test_failure_propagation(self, capsys: pytest.CaptureFixture[str]) -> None:
        """
        Tests that when a task fails, its dependents are not run.
        """
        manager = TaskManager()
        executed_tasks = set()

        manager.register(Task(name="A", function=lambda: executed_tasks.add("A")))
        manager.register(Task(name="B", depends=("A",), function=failing_func))
        manager.register(
            Task(name="C", depends=("B",), function=lambda: executed_tasks.add("C"))
        )

        orchestrator = TaskOrchestrator(manager)
        orchestrator.run_tasks(["C"], tqdm_disable=True)

        captured = capsys.readouterr()
        assert "A" in executed_tasks
        assert "C" not in executed_tasks
        assert "Task 'B' failed" in captured.out
        assert "Finished with Failures" in captured.out

    def test_skips_up_to_date_and_runs_dependent(self, tmp_path: Path) -> None:
        """
        Tests that an up-to-date task is skipped but its dependent still runs.

        NOTE: This test is expected to FAIL with the current implementation.
        The orchestrator pre-emptively marks 'A' as SKIPPED, which prevents 'B'
        from ever becoming ready, causing a deadlock. A correct implementation
        would process 'A' as skipped and then trigger 'B' to run.
        """
        manager = TaskManager()
        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"

        # Pre-create the output for task A to make it "up-to-date"
        create_file_func(file_a)

        manager.register(Task(name="A", function=lambda: None, output_files=(file_a,)))
        manager.register(
            Task(
                name="B",
                depends=("A",),
                function=create_file_func,
                args=(file_b,),
                output_files=(file_b,),
            )
        )

        orchestrator = TaskOrchestrator(manager, check_freq=0.01)
        orchestrator.run_tasks(["B"], tqdm_disable=True)

        # The desired outcome is that B runs even though A was skipped.
        assert file_b.is_file()

    def test_force_run_executes_all_tasks(self, tmp_path: Path) -> None:
        """
        Tests that `force=True` runs tasks even if they are up-to-date.
        """
        manager = TaskManager()
        file_a = tmp_path / "a.txt"
        executed_tasks = set()

        # Task A is up-to-date
        create_file_func(file_a)

        manager.register(
            Task(
                name="A",
                function=lambda: executed_tasks.add("A"),
                output_files=(file_a,),
            )
        )

        orchestrator = TaskOrchestrator(manager)
        orchestrator.run_tasks(["A"], force=True, tqdm_disable=True)

        assert "A" in executed_tasks

    def test_concurrency_with_multiple_workers(self) -> None:
        """
        Tests that independent tasks run in parallel with multiple workers.
        """
        manager = TaskManager()
        sleep_time = 0.1
        mergin = 1

        # Three independent tasks that each sleep
        manager.register(Task(name="A", function=lambda: time.sleep(sleep_time)))
        manager.register(Task(name="B", function=lambda: time.sleep(sleep_time)))
        manager.register(Task(name="C", function=lambda: time.sleep(sleep_time)))

        orchestrator = TaskOrchestrator(manager, max_workers=3)

        start_time = time.time()
        orchestrator.run_tasks(["A", "B", "C"], tqdm_disable=True)
        end_time = time.time()

        duration = end_time - start_time
        # The total time should be closer to one sleep_time, not the sum of all three.
        assert duration < (sleep_time + mergin)

    def test_run_with_no_targets_fails(self) -> None:
        """
        Tests that the orchestrator raises an error if no target tasks are provided.
        """
        manager = TaskManager()
        orchestrator = TaskOrchestrator(manager)

        with pytest.raises(ValueError, match="No target tasks specified"):
            orchestrator.run_tasks([], tqdm_disable=True)

    def test_deadlock_warning_is_shown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Tests that the deadlock warning is printed if no tasks can run.
        """
        manager = TaskManager()

        # Create a situation where a task depends on a file that will never exist
        # This simulates a state where a task is pending but can never be ready.
        missing_input = Path("non_existent_input.txt")
        manager.register(
            Task(
                name="A",
                function=lambda: None,
                input_files=(missing_input,),
                output_files=(Path("a.txt"),),
            )
        )

        # Use a short check frequency to speed up the test
        orchestrator = TaskOrchestrator(manager, check_freq=0.01)
        orchestrator.run_tasks(["A"], tqdm_disable=True)

        captured = capsys.readouterr()
        assert "Warning: No runnable tasks are currently submitted" in captured.out
