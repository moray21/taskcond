# taskcond

`taskcond` is a Pythonic task runner that executes tasks based on dependencies and file modification times, similar to `make`.

## Features

- **Pythonic Task Definition**: Define tasks as Python functions or shell commands in a `TaskFile.py`.
- **Dependency Management**: Specify dependencies between tasks to ensure they run in the correct order.
- **Incremental Builds**: Tasks are skipped if their output files are newer than their input files, saving execution time.
- **Parallel Execution**: Run independent tasks concurrently using threads or processes to speed up workflows.
- **Command-Line Interface**: A simple and intuitive CLI powered by `click` for running and listing tasks.
- **Flexible Configuration**: Configure default behaviors in your `pyproject.toml` file.
- **Cycle Detection**: Automatically detects and reports cyclic dependencies in your task graph.

## Quick Start

1.  **Installation**
    ```bash
    pip install taskcond
    ```

2.  **Create a `TaskFile.py`**
    Create a file named `TaskFile.py` in your project root and define your tasks.

    ```python
    from pathlib import Path
    from taskcond import Task, register

    # Define a task that creates a file
    register(
        Task(
            name="create_file",
            description="Create an output file.",
            shell_command="echo 'Hello, taskcond!' > output.txt",
            output_files=(Path("output.txt"),),
        )
    )

    # Define a task that depends on the first one
    register(
        Task(
            name="process_file",
            description="Process the created file.",
            shell_command="cat output.txt",
            depends=("create_file",),
            input_files=(Path("output.txt"),),
        )
    )
    ```

3.  **Run Tasks**
    Use the `taskcond` CLI to run your tasks.

    ```bash
    # List available tasks
    taskcond list

    # Run a specific task and its dependencies
    taskcond run process_file
    ```

    The `process_file` task will only run if `output.txt` has been modified or is missing.

## Configuration

You can configure `taskcond` by adding a `[tool.taskcond]` section to your `pyproject.toml`:

```toml
[tool.taskcond]
taskfile = "TaskFile.py"  # Path to the task definition file
force = false             # Force execution of all tasks
n_jobs = 1                # Number of parallel jobs (-1 for all cores)
use_processes = false     # Use ProcessPoolExecutor instead of ThreadPoolExecutor
visible_progressbar = true # Show a progress bar during execution
```

CLI options will always override the settings in `pyproject.toml`.
