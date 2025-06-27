import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True, eq=True, unsafe_hash=True)
class Task:
    """
    Represents a single, executable unit of work within a dependency graph.

    A task can be defined by either a Python function or a shell command. Its
    execution can be made conditional based on the existence and modification
    times of specified input and output files.

    Parameters
    ----------
    name : str
        The unique identifier for the task.
    function : Callable[..., None] | None, optional
        The Python function to be executed.
    depends : tuple[str, ...], optional
        A tuple of names of other tasks that must be completed before this one.
    args : tuple[Any, ...], optional
        Arguments to be passed to the `function` or appended to the `shell_command`.
    description : str, optional
        A human-readable description of what the task does.
    output_files : tuple[Path, ...] | None, optional
        A tuple of file paths that this task is expected to create or modify.
    input_files : tuple[Path, ...] | None, optional
        A tuple of file paths that this task uses as input.
    shell_command : str | None, optional
        A shell command to be executed.
    """

    name: str
    function: Callable[..., None] | None = None
    depends: tuple[str, ...] = field(default_factory=tuple)
    args: tuple[Any, ...] = field(default_factory=tuple)
    description: str = ""
    output_files: tuple[Path, ...] | None = None
    input_files: tuple[Path, ...] | None = None
    shell_command: str | None = None

    def should_run(self) -> bool:
        """
        Determines whether the task needs to be executed.

        This method implements up-to-date checking based on file dependencies:
        1. If `output_files` and `input_files` are both defined, it checks if
           any output file is missing or if any input file is newer than the
           oldest output file (similar to how `make` works).
        2. If only `output_files` are defined, it checks if all output files
           exist. This is useful for tasks like downloading files.
        3. If file dependencies are not specified, the task is always considered
           to require execution.

        Returns
        -------
        bool
            True if the task should be run, False if it is up-to-date.
        """
        # Case 1: Both input and output files are specified for dependency checking.
        if self.output_files is not None and self.input_files is not None:
            # If any output file does not exist, the task must be run.
            for output_file in self.output_files:
                if not output_file.exists():
                    return True

            # Get the modification time of the most recently updated output file.
            # Note: This will raise an error if self.output_files is not empty but contains only non-existent files,
            # but the loop above prevents this scenario.
            latest_output_mtime = max(
                f.stat().st_mtime for f in self.output_files if f.exists()
            )

            # Check each input file against the output files.
            for input_file in self.input_files:
                # If an input file is missing, something is wrong, but we'll
                # let the dependency chain handle it. For this task's purpose,
                # we can't compare times, so we assume it might need to run.
                if not input_file.exists():
                    return True
                # If any input file is newer than the latest output file, the task is stale and must be run.
                if input_file.stat().st_mtime > latest_output_mtime:
                    return True

            # If all checks pass, the task is up-to-date.
            return False

        # Case 2: Only output files are specified.
        # This is useful for tasks that only create targets, like downloading a file.
        elif self.output_files is not None and self.input_files is None:
            # The task should run if any of the output files are missing.
            return not all(f.exists() for f in self.output_files)

        # Case 3: No file-based dependency checking is configured.
        # The task is always considered to need execution.
        else:
            return True

    def execute(self) -> None:
        """
        Executes the task's defined action.

        If `shell_command` is provided, it is executed first. Then, if
        `function` is provided, it is executed.

        Raises
        ------
        RuntimeError
            If the shell command or the Python function fails during execution.
        """
        # If a shell command is defined, execute it.
        if self.shell_command is not None:
            try:
                # Use shlex.split for robust parsing of shell-like syntax,
                # correctly handling quotes and spaces.
                command = shlex.split(self.shell_command)
                # Append any additional arguments.
                command += list(self.args)

                print(f"run: {self.name} from shell")
                # Execute the command, raising an exception if it returns a non-zero exit code.
                subprocess.run(command, check=True)
                print()

            except subprocess.CalledProcessError as e:
                # Wrap the process error in a more generic RuntimeError for the orchestrator.
                raise RuntimeError("Shell command failed") from e

        # If a Python function is defined, execute it after the shell command (if any).
        if self.function is not None:
            try:
                print(f"run: {self.name} from python")
                # Call the function, unpacking the stored arguments.
                self.function(*self.args)
                print()
            except Exception as e:
                # Wrap any exception from the function in a RuntimeError.
                raise RuntimeError(
                    f"Python function '{self.function.__name__}' failed: {e}"
                ) from e
