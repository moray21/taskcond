from pathlib import Path

import taskcond
from taskcond import Task, register

root_dir = Path(__file__).parent


# format
register(Task(name="black", shell_command=f"black {str(root_dir)}"))
register(Task(name="isort", shell_command=f"isort {str(root_dir)}"))
register(
    Task(name="format", depends=("black", "isort"), description="run black and isort")
)

# lint
register(Task(name="__check_black", shell_command=f"black --check {str(root_dir)}"))
register(
    Task(name="__check_isort", shell_command=f"isort --check --diff {str(root_dir)}")
)
register(Task(name="flake8", shell_command=f"flake8 {str(root_dir)}"))
register(Task(name="mypy", shell_command=f"mypy {str(root_dir)}"))
register(
    Task(
        name="lint",
        depends=("__check_black", "__check_isort", "flake8", "mypy"),
        description="run flake8 and mypy",
    )
)

# test
register(Task(name="test", shell_command="coverage run -m pytest"))
register(
    Task(
        name="coverage",
        depends=("test",),
        shell_command="coverage report -m",
        description="do test and measure coverage",
    )
)

# check
register(Task(name="check", depends=("format", "lint", "coverage")))


# build
wheel_file = root_dir / "dist" / f"taskcond-{taskcond.__version__}-py3-none-any.whl"
tgz_file = root_dir / "dist" / f"taskcond-{taskcond.__version__}.tar.gz"

register(
    Task(
        name="build",
        shell_command="python -m build",
        output_files=(wheel_file, tgz_file),
        description="build package",
    )
)
register(
    Task(
        name="upload_package",
        depends=("build",),
        shell_command=f"twine upload {str(wheel_file)} {str(tgz_file)}",
        input_files=(wheel_file, tgz_file),
        description="upload package to PyPI",
    )
)
