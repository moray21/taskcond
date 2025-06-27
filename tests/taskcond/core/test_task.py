import time
from pathlib import Path

import pytest

from taskcond.core.task import Task


def dummy_func() -> None:
    """A dummy function for testing."""
    pass


def failing_func() -> None:
    """A dummy function that always fails."""
    raise ValueError("This function is designed to fail.")


def func_with_args(a: int, b: str) -> None:
    """A dummy function that accepts arguments."""
    assert isinstance(a, int)
    assert isinstance(b, str)


class TestTask:
    """Unit tests for the Task class."""

    def test_should_run_no_file_deps(self) -> None:
        """
        Tests that should_run() is always True when no file dependencies are specified.
        """
        task = Task(name="test", function=dummy_func)
        assert task.should_run()

    def test_should_run_only_outputs_exist(self, tmp_path: Path) -> None:
        """
        Tests should_run() with only output files, which all exist.
        """
        output_file = tmp_path / "output.txt"
        output_file.touch()
        task = Task(name="test", function=dummy_func, output_files=(output_file,))
        assert not task.should_run()

    def test_should_run_only_outputs_missing(self, tmp_path: Path) -> None:
        """
        Tests should_run() with only output files, where one is missing.
        """
        output_file = tmp_path / "output.txt"
        task = Task(name="test", function=dummy_func, output_files=(output_file,))
        assert task.should_run()

    def test_should_run_inputs_and_outputs_up_to_date(self, tmp_path: Path) -> None:
        """
        Tests should_run() when outputs are newer than inputs.
        """
        input_file = tmp_path / "input.txt"
        output_file = tmp_path / "output.txt"

        input_file.touch()
        time.sleep(0.01)  # Ensure a time difference
        output_file.touch()

        task = Task(
            name="test",
            function=dummy_func,
            input_files=(input_file,),
            output_files=(output_file,),
        )
        assert not task.should_run()

    def test_should_run_input_is_newer(self, tmp_path: Path) -> None:
        """
        Tests should_run() when an input file is newer than an output file.
        """
        input_file = tmp_path / "input.txt"
        output_file = tmp_path / "output.txt"

        output_file.touch()
        time.sleep(0.01)  # Ensure a time difference
        input_file.touch()

        task = Task(
            name="test",
            function=dummy_func,
            input_files=(input_file,),
            output_files=(output_file,),
        )
        assert task.should_run()

    def test_should_run_output_is_missing(self, tmp_path: Path) -> None:
        """
        Tests should_run() when an output file is missing.
        """
        input_file = tmp_path / "input.txt"
        output_file = tmp_path / "output.txt"
        input_file.touch()

        task = Task(
            name="test",
            function=dummy_func,
            input_files=(input_file,),
            output_files=(output_file,),
        )
        assert task.should_run()

    def test_should_run_input_is_missing(self, tmp_path: Path) -> None:
        """
        Tests should_run() when an input file is missing.
        """
        input_file = tmp_path / "input.txt"
        output_file = tmp_path / "output.txt"
        output_file.touch()

        task = Task(
            name="test",
            function=dummy_func,
            input_files=(input_file,),
            output_files=(output_file,),
        )
        assert task.should_run()

    def test_execute_successful_shell_command(self) -> None:
        """
        Tests that a successful shell command executes without error.
        """
        task = Task(name="test", shell_command="echo 'Success'")
        task.execute()

    def test_execute_failing_shell_command(self) -> None:
        """
        Tests that a failing shell command raises a RuntimeError.
        """
        task = Task(name="test", shell_command="test")
        with pytest.raises(RuntimeError, match="Shell command failed"):
            task.execute()

    def test_execute_successful_function(self) -> None:
        """
        Tests that a successful Python function executes without error.
        """
        task = Task(name="test", function=dummy_func)
        task.execute()

    def test_execute_failing_function(self) -> None:
        """
        Tests that a failing Python function raises a RuntimeError.
        """
        task = Task(name="test", function=failing_func)
        with pytest.raises(RuntimeError, match="Python function 'failing_func' failed"):
            task.execute()

    def test_execute_function_with_args(self) -> None:
        """
        Tests that arguments are correctly passed to a Python function.
        """
        task = Task(name="test", function=func_with_args, args=(123, "test_string"))
        task.execute()
