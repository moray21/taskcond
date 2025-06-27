from enum import Enum, auto
from types import MappingProxyType

from .task import Task


class VisitStatus(Enum):
    """
    Enumeration for the visitation status of a task during graph traversal.

    This is used for cycle detection within the task dependency graph.
    """

    UNVISITED = auto()  # The node has not been visited yet.
    VISITING = auto()  # The node is currently in the recursion stack.
    VISITED = auto()  # The node and all its descendants have been fully visited.


class TaskManager:
    """
    A singleton class to manage the registration and retrieval of tasks.

    This manager ensures that each task has a unique name and provides
    methods to access tasks and validate the integrity of the dependency graph,
    such as checking for cyclic dependencies.
    """

    def __new__(cls) -> "TaskManager":
        """
        Creates and returns the singleton instance of the TaskManager.
        """
        if not hasattr(cls, "_instance"):
            # Create the singleton instance if it doesn't exist.
            cls._instance = super(TaskManager, cls).__new__(cls)
            # Call the one-time initializer.
            cls._instance.__initialize_once__()
        return cls._instance

    def __initialize_once__(self) -> None:
        """Initializes the internal task storage. Called only once."""
        self.__tasks: dict[str, Task] = {}

    def register(self, task: Task) -> None:
        """
        Registers a new task.

        Parameters
        ----------
        task : Task
            The task instance to register.

        Raises
        ------
        ValueError
            If a task with the same name is already registered.
        """
        if task.name in self.__tasks.keys():
            raise ValueError(f"Task with name '{task.name}' already registered.")
        self.__tasks[task.name] = task

    @property
    def task_dicts(self) -> MappingProxyType[str, Task]:
        """
        Returns a read-only view of the tasks dictionary.

        Returns
        -------
        MappingProxyType[str, Task]
            A dictionary-like object mapping task names to Task instances.
        """
        return MappingProxyType(self.__tasks)

    @property
    def tasks(self) -> list[Task]:
        """
        Returns a list of all registered task instances.

        Returns
        -------
        list[Task]
            A list of all tasks.
        """
        return list(self.__tasks.values())

    @property
    def task_names(self) -> list[str]:
        """
        Returns a list of all registered task names.

        Returns
        -------
        list[str]
            A list of the names of all tasks.
        """
        return list(self.__tasks.keys())

    def get_task(self, name: str) -> Task:
        """
        Retrieves a task by its name.

        Parameters
        ----------
        name : str
            The name of the task to retrieve.

        Returns
        -------
        Task
            The task instance corresponding to the given name.

        Raises
        ------
        ValueError
            If no task with the given name is found.
        """
        if name not in self.__tasks.keys():
            raise ValueError(f"Task '{name}' is not defined.")
        return self.__tasks[name]

    def validate_cycles(self) -> None:
        """
        Validates the task dependency graph for cycles.

        This method performs a Depth-First Search (DFS) traversal of the graph
        to ensure there are no cyclic dependencies among the registered tasks.

        Raises
        ------
        ValueError
            If a task depends on an unregistered task.
            If a cyclic dependency is detected in the graph.
        """
        # A dictionary to track the visitation status of each task (node).
        task_status_dict: dict[str, VisitStatus] = {
            task.name: VisitStatus.UNVISITED for task in self.tasks
        }
        # A stack to keep track of the current traversal path.
        # This is used to report the exact cycle if one is found.
        recursion_stack: list[str] = []

        def dfs_visit(task: Task) -> None:
            """
            A recursive helper function for performing DFS to detect cycles.

            This function is nested to have access to `task_status_dict` and
            `recursion_stack` from the outer scope.

            Parameters
            ----------
            task : Task
                The current task (node) being visited in the traversal.
            """
            # Mark the current task as 'visiting' and add it to the recursion path.
            task_status_dict[task.name] = VisitStatus.VISITING
            recursion_stack.append(task.name)

            # Recursively visit all dependencies of the current task.
            for dep_name in task.depends:
                # Check for unregistered tasks.
                if dep_name not in self.__tasks:
                    raise ValueError(
                        f"Task '{task.name}' depends on unknown task '{dep_name}'. "
                        + "Please ensure all dependencies are registered tasks."
                    )

                # If a dependency is already in the 'visiting' state, we have found a cycle.
                if task_status_dict[dep_name] == VisitStatus.VISITING:
                    # Reconstruct the cycle path from the recursion stack for a clear error message.
                    cycle_start_index = recursion_stack.index(dep_name)
                    cycle_path_list = recursion_stack[cycle_start_index:] + [dep_name]
                    cycle_path = " -> ".join(cycle_path_list)
                    raise ValueError(f"Cyclic dependency detected: {cycle_path}")

                # If the dependency hasn't been visited yet, recurse into it.
                if task_status_dict[dep_name] == VisitStatus.UNVISITED:
                    dep_task = self.get_task(dep_name)
                    dfs_visit(dep_task)

            # Backtrack: remove the task from the path and mark it as fully 'visited'.
            recursion_stack.pop()
            task_status_dict[task.name] = VisitStatus.VISITED

        # Iterate through all tasks to handle disconnected components in the graph.
        for task in self.tasks:
            # If a task hasn't been visited yet, start a new DFS traversal from it.
            if task_status_dict[task.name] == VisitStatus.UNVISITED:
                dfs_visit(task)


def register(task: Task) -> None:
    """
    A convenience function to register a task with the global TaskManager.

    This function provides a simple, module-level interface for task registration.

    Parameters
    ----------
    task : Task
        The task instance to register.
    """
    manager = TaskManager()
    manager.register(task)
