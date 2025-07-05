import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from taskcond.cli import RunConfig, cli
from taskcond.core.manager import TaskManager


@pytest.fixture(scope="function")
def tomlfile(tmp_path: Path) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(
        textwrap.dedent(
            """
            [tool.taskcond]
            n_jobs = 4
            force = true
            visible_progressbar = true
            """
        )
    )
    return path


@pytest.fixture(scope="function")
def taskfile(tmp_path: Path) -> Path:
    path = tmp_path / "TaskFile.py"
    (tmp_path / "input.txt").touch()
    path.write_text(
        textwrap.dedent(
            """
            from taskcond import Task, register
            from pathlib import Path

            def task_a_func() -> None:  # pragma: no cover
                Path("a.txt").touch()

            def task_b_func() -> None:  # pragma: no cover
                Path("b.txt").touch()

            register(
                Task(
                    name="A",
                    function=task_a_func,
                    description="Task A",
                    input_files=(Path("input.txt"),),
                    output_files=(Path("a.txt"),),
                )
            )
            register(
                Task(
                    name="B",
                    depends=("A",),
                    function=task_b_func,
                    description="Task B",
                    output_files=(Path("b.txt"),),
                )
            )
            register(
                Task(
                    name="__hidden_task",
                    function=lambda: None,
                    description="This is a hidden task",
                    displayed=False,
                )
            )
            """
        )
    )
    return path


@pytest.fixture(scope="function")
def taskfile_with_cycle_depends(tmp_path: Path) -> Path:
    path = tmp_path / "TaskFile.py"
    path.write_text(
        textwrap.dedent(
            """
            from taskcond import Task, register

            register(Task(name="C", depends=("D",), function=lambda: None))
            register(Task(name="D", depends=("C",), function=lambda: None))
            """
        )
    )
    return path


@pytest.fixture(scope="function")
def taskfile_with_error(tmp_path: Path) -> Path:
    path = tmp_path / "TaskFile.py"
    path.write_text(
        textwrap.dedent(
            """
            import non_existent_module
            """
        )
    )
    return path


class TestRunConfig:
    """Unit tests for the RunConfig class."""

    def test_load_defaults(
        self, taskfile: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests loading with default values when no config file is present."""
        monkeypatch.chdir(taskfile.parent)
        config = RunConfig.load()

        assert not config.force
        assert config.n_jobs is None
        assert not config.use_processes
        assert not config.visible_progressbar

    def test_load_from_pyproject(
        self, tomlfile: Path, taskfile: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests loading configuration from pyproject.toml."""
        monkeypatch.chdir(tomlfile.parent)
        config = RunConfig.load()

        assert config.n_jobs == 4
        assert config.force
        assert not config.use_processes
        assert config.visible_progressbar

    def test_load_kwargs_override_pyproject(
        self, tomlfile: Path, taskfile: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests that kwargs (from CLI) override pyproject.toml settings."""
        monkeypatch.chdir(tomlfile.parent)
        config = RunConfig.load(force=False, n_jobs=8)

        # This value was not overridden, so it should come from the file.
        assert config.n_jobs == 8
        assert not config.force
        assert not config.use_processes
        assert config.visible_progressbar

    def test_load_tasks_from_file_success(
        self, taskfile: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests that tasks are loaded successfully from the taskfile."""
        monkeypatch.chdir(taskfile.parent)

        RunConfig.load()
        manager = TaskManager()

        assert "A" in manager.task_names
        assert "B" in manager.task_names
        assert "__hidden_task" in manager.task_names
        assert manager.get_task("B").depends == ("A",)

    def test_load_tasks_from_file_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests that a ValueError is raised if the taskfile is not found."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="Task file 'TaskFile.py' not found"):
            RunConfig.load()

    def test_load_tasks_from_file_with_error(
        self, taskfile_with_error: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests that a RuntimeError is raised if the taskfile has an error."""
        monkeypatch.chdir(taskfile_with_error.parent)
        with pytest.raises(RuntimeError, match="Error loading tasks from"):
            RunConfig.load()

    def test_load_with_not_pyfile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        file = Path("not_a_pyfile.txt")
        file.write_text("This is not a Python file.")

        with pytest.raises(
            RuntimeError,
            match="Error: Could not load module spec for 'not_a_pyfile.txt'.",
        ):
            RunConfig.load(taskfile=file)


class TestCliCommands:
    """Unit tests for the CLI commands."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Provides a Click CliRunner instance."""
        return CliRunner()

    def test_list_command_success(
        self, runner: CliRunner, taskfile: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests the 'list' command with a valid TaskFile."""
        monkeypatch.chdir(taskfile.parent)
        result = runner.invoke(cli, ["list"])

        expected = (
            "Available Tasks:\n"
            "  A: Task A\n"
            "    Outputs: a.txt\n"
            "    Inputs: input.txt\n"
            "  B: Task B\n"
            "    Depends on: A\n"
            "    Outputs: b.txt\n"
        )

        assert result.exit_code == 0
        print(result.output)
        print(expected)
        assert result.output == expected

    def test_list_command_no_tasks(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests the 'list' command when the TaskFile is empty."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "TaskFile.py").write_text("# No tasks here")

        result = runner.invoke(cli, ["list"])

        assert result.exit_code != 0
        assert isinstance(result.exception, RuntimeError)
        assert "No tasks found" in str(result.exception)

    def test_list_command_cycle_detection(
        self,
        runner: CliRunner,
        taskfile_with_cycle_depends: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Tests that 'list' command detects and reports cycles."""
        monkeypatch.chdir(taskfile_with_cycle_depends.parent)

        result = runner.invoke(cli, ["list"])

        assert result.exit_code != 0
        assert isinstance(result.exception, RuntimeError)
        assert "Cyclic dependency detected" in str(result.exception)

    def test_run_command_success(
        self, runner: CliRunner, taskfile: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests a successful 'run' command execution."""
        monkeypatch.chdir(taskfile.parent)

        result = runner.invoke(cli, ["run", "B", "-s"])

        assert result.exit_code == 0
        assert "All tasks completed successfully" in result.output
        assert Path("a.txt").is_file()
        assert Path("b.txt").is_file()

    def test_run_command_no_tasks(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests the 'run' command when the TaskFile is empty."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "TaskFile.py").write_text("# No tasks here")

        result = runner.invoke(cli, ["run"])

        assert result.exit_code != 0
        assert isinstance(result.exception, RuntimeError)
        assert "No tasks found" in str(result.exception)

    def test_run_command_no_target(
        self, runner: CliRunner, taskfile: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests 'run' command without specifying a target task."""
        monkeypatch.chdir(taskfile.parent)

        result = runner.invoke(cli, ["run"])

        assert result.exit_code != 0
        assert isinstance(result.exception, ValueError)
        assert "No target tasks specified" in str(result.exception)

    def test_run_command_unknown_task(
        self, runner: CliRunner, taskfile: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests 'run' command with a non-existent task name."""
        monkeypatch.chdir(taskfile.parent)

        result = runner.invoke(cli, ["run", "Z"])

        assert result.exit_code != 0
        assert isinstance(result.exception, ValueError)
        assert "Task 'Z' not found" in str(result.exception)
