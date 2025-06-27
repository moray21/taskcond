import importlib.util
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from taskcond.core import TaskManager, TaskOrchestrator


@dataclass
class RunConfig:
    """
    Configuration for running tasks.

    This class holds settings for task execution, which can be loaded from a
    `pyproject.toml` file and overridden by command-line arguments. It also
    handles the loading of tasks from the specified task file.

    Attributes
    ----------
    taskfile : Path
        The path to the file containing task definitions.
    force : bool
        If True, tasks will be executed regardless of their freshness.
    n_jobs : int | None
        The number of parallel workers to use for execution.
    use_processes : bool
        If True, use `ProcessPoolExecutor` instead of `ThreadPoolExecutor`.
    visible_progressbar : bool
        If True, the progress bar will be displayed during execution.
    """

    taskfile: Path = Path("TaskFile.py")
    force: bool = False
    n_jobs: int | None = None
    use_processes: bool = False
    visible_progressbar: bool = False

    @classmethod
    def load(cls, **kwargs: Any) -> "RunConfig":
        """
        Load configuration from `pyproject.toml` and merge with kwargs.

        This method first looks for a `pyproject.toml` file and reads the
        `[tool.taskcond]` section. It then updates this configuration with
        any values provided in `kwargs`, which typically come from command-line
        arguments.

        Parameters
        ----------
        **kwargs : Any
            Keyword arguments to override the configuration loaded from the file.

        Returns
        -------
        RunConfig
            An instance of the RunConfig class.
        """
        pyproject_path = Path("pyproject.toml")
        taskcond_dict: dict[str, Any] = {}
        if pyproject_path.is_file():
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)

                # Safely get the [tool.taskcond] table
                tool_dict = data.get("tool", {})
                taskcond_dict = tool_dict.get("taskcond", {})

        # CLI arguments override pyproject.toml settings
        taskcond_dict.update(kwargs)

        return cls(**taskcond_dict)

    def __post_init__(self) -> None:
        """
        Perform post-initialization processing.

        Converts the `taskfile` attribute to a `Path` object and triggers
        the loading of tasks from that file.
        """
        self.taskfile = Path(self.taskfile)
        self.__load_tasks_from_file()

    def __load_tasks_from_file(self) -> None:
        """
        Dynamically load tasks from the specified task file.

        This method finds the task file, creates a module spec from it,
        and executes the module to register the tasks defined within.

        Raises
        ------
        ValueError
            If the task file is not found.
        RuntimeError
            If the module spec cannot be created or the module fails to load.
        """
        if not self.taskfile.is_file():
            raise ValueError(f"Error: Task file '{self.taskfile}' not found.")

        module_name = f"user_tasks_{self.taskfile.stem.replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, self.taskfile)
        if spec is None or spec.loader is None:
            raise RuntimeError(
                f"Error: Could not load module spec for '{self.taskfile}'."
            )

        user_tasks_module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = user_tasks_module

        try:
            # Execute the module, which should call `taskcond.register`
            spec.loader.exec_module(user_tasks_module)
        except Exception as e:
            raise RuntimeError(f"Error loading tasks from '{self.taskfile}': {e}")


# ------------------------------ CLI Command Group ------------------------------
@click.group()
def cli() -> None:
    """A command-line tool for conditional task execution."""
    pass


# ------------------------------ 'run' Command ------------------------------
@cli.command(name="run")
@click.argument("task_name_list", nargs=-1)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Force execution, ignoring dependencies' freshness.",
)
@click.option(
    "--n_jobs",
    "-j",
    type=int,
    default=None,
    help="Number of parallel workers. Defaults to 1. Use -1 for all available CPU cores.",
)
@click.option(
    "--use_processes",
    is_flag=True,
    help="Use ProcessPoolExecutor instead of ThreadPoolExecutor for parallel execution.",
)
@click.option(
    "--visible_progressbar",
    "-s",
    is_flag=True,
    help="Show the progress bar during execution.",
)
@click.pass_context
def run(
    ctx: click.Context,
    task_name_list: tuple[str, ...],
    force: bool,
    n_jobs: int | None,
    use_processes: bool,
    visible_progressbar: bool,
) -> None:
    """
    Run a specific task or the default task.

    If no tasks are specified, this command will raise an error.

    Parameters
    ----------
    ctx : click.Context
        The Click context object.
    task_name_list : tuple[str, ...]
        A list of task names to execute.
    force : bool
        Flag to force task execution.
    n_jobs : int | None
        Number of parallel jobs.
    use_processes : bool
        Flag to use processes instead of threads.
    visible_progressbar : bool
        Flag to make the progress bar visible.
    """
    # Collect CLI options that were explicitly set by the user (not defaults).
    # These will override any settings from `pyproject.toml`.
    kwargs = {
        attr: value
        for attr, value in locals().items()
        if attr not in ["ctx", "task_name_list"]
        and ctx.get_parameter_source(attr) != click.core.ParameterSource.DEFAULT
    }
    # Load configuration, which also loads the tasks from the task file.
    config = RunConfig.load(**kwargs)

    task_manager = TaskManager()
    all_task_names = task_manager.task_names
    if len(all_task_names) == 0:
        raise RuntimeError(f"No tasks found in '{config.taskfile}'.")

    if not task_name_list:
        raise ValueError(
            "No target tasks specified. Use 'taskcond list' to see available tasks."
        )

    # Validate that all specified tasks exist.
    target_task_list: list[str] = []
    for task_name in task_name_list:
        if task_name not in all_task_names:
            raise ValueError(
                f"Error: Task '{task_name}' not found. "
                + "Use 'taskcond list' to see available tasks."
            )
        target_task_list.append(task_name)

    # Set up and run the orchestrator.
    orchestrator = TaskOrchestrator(
        task_manager, max_workers=config.n_jobs, use_processes=config.use_processes
    )
    orchestrator.run_tasks(
        target_task_list,
        force=config.force,
        tqdm_disable=(not config.visible_progressbar),
    )


# ------------------------------ 'list' Command ------------------------------
@cli.command(name="list")
def list_tasks() -> None:
    """
    List all available tasks defined in the specified file.

    This command loads tasks from the task file (default: TaskFile.py)
    and prints their names, descriptions, dependencies, and I/O files.
    It also performs a cycle check on the dependency graph.
    """
    # Load configuration to trigger loading tasks from the task file.
    config = RunConfig.load()

    task_manager = TaskManager()
    all_tasks = task_manager.tasks
    if not all_tasks:
        raise RuntimeError(f"No tasks found in '{config.taskfile}'.")

    print("Available Tasks:")
    for task in all_tasks:
        print(f"  {task.name}: {task.description}")
        if task.depends:
            print(f"    Depends on: {', '.join(task.depends)}")
        if task.output_files is not None:
            print(f"    Outputs: {', '.join(map(str, task.output_files))}")
        if task.input_files is not None:
            print(f"    Inputs: {', '.join(map(str, task.input_files))}")

    # After listing, validate the graph for any cyclic dependencies.
    try:
        task_manager.validate_cycles()
    except ValueError as e:
        # If a cycle is found, report it as a critical warning.
        raise RuntimeError(
            f"Warning: Cyclic dependency detected! This graph cannot be executed: {e}"
        )


if __name__ == "__main__":  # pragma: no cover
    cli()
