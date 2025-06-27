import os
import time
from collections import defaultdict, deque
from concurrent.futures import (
    Executor,
    Future,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
)
from dataclasses import dataclass
from enum import IntEnum, auto

from tqdm import tqdm

from .manager import TaskManager
from .task import Task


class RunStatus(IntEnum):
    """
    Enumeration for the execution status of a task during orchestration.
    """

    PENDING = auto()  # Task is waiting for its dependencies to complete.
    RUNNING = auto()  # Task is currently being executed.
    COMPLETED = auto()  # Task has finished successfully.
    SKIPPED = auto()  # Task execution was skipped (e.g., already up-to-date).
    FAILED = auto()  # Task execution failed.


class RemainingDependenciesCount:
    """
    A simple counter to track the number of unmet dependencies for a task.

    Parameters
    ----------
    count : int, default 0
        The initial count of remaining dependencies.
    """

    def __init__(self, count: int = 0) -> None:
        """Initializes the dependency counter."""
        self.__count = count

    def countdown(self) -> None:
        """
        Decrements the internal counter by one.
        """
        self.__count -= 1

    @property
    def is_zero(self) -> bool:
        """
        Checks if the counter has reached zero.

        Returns
        -------
        bool
            True if the count is 0, False otherwise.
        """
        return self.__count == 0


@dataclass
class TaskState:
    """
    Represents the state of a single task within the execution graph.
    """

    task: Task
    status: RunStatus
    remaining_dependencies_count: RemainingDependenciesCount

    @classmethod
    def create(cls, task: Task) -> "TaskState":
        """
        Creates a new TaskState instance for a given task.

        The initial status is set to PENDING, and the dependency count is
        initialized based on the task's `depends` attribute.

        Parameters
        ----------
        task : Task
            The task for which to create the state.

        Returns
        -------
        TaskState
            A new TaskState instance.
        """
        return cls(
            task, RunStatus.PENDING, RemainingDependenciesCount(count=len(task.depends))
        )

    @property
    def is_ready(self) -> bool:
        """
        Checks if the task is ready to be executed.

        A task is ready if it is pending and all its dependencies are met.
        """
        return (
            self.status == RunStatus.PENDING
            and self.remaining_dependencies_count.is_zero
            and (
                (self.task.input_files is None)
                or all(input.is_file() for input in self.task.input_files)
            )
        )

    @property
    def is_pending(self) -> bool:
        """Checks if the task is in the PENDING state."""
        return self.status == RunStatus.PENDING

    @property
    def is_failed(self) -> bool:
        """Checks if the task is in the FAILED state."""
        return self.status == RunStatus.FAILED

    @property
    def is_finished(self) -> bool:
        """Checks if the task has reached a terminal state."""
        return self.status in [RunStatus.COMPLETED, RunStatus.SKIPPED, RunStatus.FAILED]


class TaskOrchestrator:
    """
    Coordinates the execution of a graph of tasks.

    This class is responsible for taking a set of target tasks, building the
    full dependency graph, and executing the tasks in the correct order using
    a thread or process pool. It handles task dependencies, concurrency,
    failure propagation, and skipping of up-to-date tasks.
    """

    def __init__(
        self,
        task_manager: TaskManager,
        max_workers: int | None = None,
        use_processes: bool = False,
        check_freq: float = 0.1,
    ) -> None:
        """
        Initializes the TaskOrchestrator.

        Parameters
        ----------
        task_manager : TaskManager
            The manager containing all registered tasks.
        max_workers : int, optional
            The maximum number of worker threads or processes.
            If None, it defaults to 1 (sequential execution).
            If -1, it uses the number of CPUs.
        use_processes : bool, default False
            If True, uses ProcessPoolExecutor for execution.
            If False, uses ThreadPoolExecutor.
        check_freq : float, default 0.1
            The frequency in seconds to check for completed tasks.

        """
        # Validate the dependency graph for cycles before proceeding.
        task_manager.validate_cycles()

        if max_workers is None:
            max_workers = 1
        if max_workers == -1:
            max_workers = os.cpu_count()

        self.__task_manager = task_manager
        self.__max_workers = max_workers
        self.__cls_executor = (
            ProcessPoolExecutor if use_processes else ThreadPoolExecutor
        )
        self.__check_freq = check_freq

    def run_tasks(
        self,
        target_tasks_names: list[str],
        force: bool = False,
        tqdm_disable: bool | None = False,
    ) -> None:
        """
        Executes a set of target tasks and their dependencies.

        Parameters
        ----------
        target_tasks_names : list[str]
            A list of names of the final tasks to be executed.
        force : bool, default False
            If True, forces all tasks in the execution graph to run,
            ignoring their `should_run()` status.
        tqdm_disable : bool or None, default False
            If True, disables the tqdm progress bar.

        """
        # 1. Build the execution graph and initialize task states.
        total_tasks_to_run, task_states, reverse_dependencies = (
            self.__build_execution_graph(target_tasks_names)
        )

        future_dict: dict[Future[None], Task] = {}
        with (
            self.__cls_executor(max_workers=self.__max_workers) as executor,
            tqdm(
                total=total_tasks_to_run,
                unit="task",
                desc="Overall Progress",
                disable=tqdm_disable,
            ) as pbar,
        ):
            # 2. Submit initial tasks that have no dependencies.
            self.__do_ready_tasks(
                pbar, executor, task_states, reverse_dependencies, future_dict, force
            )

            # 3. Main loop: monitor running tasks and submit new ones as they become ready.
            while True:
                # Exit condition: all tasks have reached a finished state.
                if all(state.is_finished for state in task_states.values()):
                    break

                # 4. Process completed futures.
                completed_futures: list[Future[None]] = []
                for future, task in future_dict.items():
                    if future.done():
                        completed_futures.append(future)
                        exception = future.exception()
                        if exception is not None:
                            # The task raised an exception.
                            print(f"\nTask '{task.name}' failed: {exception}")
                            status = RunStatus.FAILED
                        else:
                            # The task completed without errors.
                            status = RunStatus.COMPLETED
                        # Mark the task as completed/failed and update dependencies.
                        self.__mark_task_completed(
                            pbar, task_states, reverse_dependencies, task, status
                        )

                # Remove completed futures from the dictionary of running tasks.
                future_dict = {
                    future: task
                    for future, task in future_dict.items()
                    if future not in completed_futures
                }

                # 5. Submit any new tasks that are now ready to run.
                self.__do_ready_tasks(
                    pbar,
                    executor,
                    task_states,
                    reverse_dependencies,
                    future_dict,
                    force,
                )

                # Deadlock/Stall detection: No tasks are running, but some are still pending.
                if len(future_dict) == 0 and any(
                    state.is_pending for state in task_states.values()
                ):
                    print("\n")
                    print(
                        "Warning: No runnable tasks are currently submitted, but some tasks are still pending."
                        + "This might indicate an undetected cycle, "
                        + "a task depending on an untracked change, or a logic error."
                    )
                    break

                # 6. Wait for a short interval before checking again.
                time.sleep(self.__check_freq)

        # Final summary report.
        print("\n")
        print("-" * 20)
        failed_task_name_list = [
            task.name for task, state in task_states.items() if state.is_failed
        ]
        if failed_task_name_list:
            print(
                f"--- Execution Finished with Failures ({len(failed_task_name_list)} tasks failed) ---"
            )
            print(f"Failed tasks: {', '.join(failed_task_name_list)}")
        else:
            print("--- All tasks completed successfully (or skipped) ---")

    def __build_execution_graph(
        self, target_tasks_names: list[str]
    ) -> tuple[int, dict[Task, TaskState], dict[str, set[Task]]]:
        """
        Builds the necessary data structures for task execution.

        This method performs a traversal of the dependency graph starting from
        the target tasks to identify all tasks that need to be considered for
        execution.

        Parameters
        ----------
        target_tasks_names : list[str]
            The names of the final target tasks.

        Returns
        -------
        tuple[int, dict[Task, TaskState], dict[str, set[Task]]]
            A tuple containing:
            - The total number of tasks that need to be run (not skipped).
            - A dictionary mapping each Task to its initial TaskState.
            - A dictionary for reverse dependencies (task_name -> set of tasks that depend on it).
        """

        if len(target_tasks_names) == 0:
            raise ValueError("No target tasks specified for execution.")

        # Collect all tasks required for the run (targets and their dependencies).
        all_tasks: set[Task] = set()
        queue = deque(target_tasks_names)
        while len(queue) != 0:
            task_name = queue.popleft()
            task = self.__task_manager.get_task(task_name)
            all_tasks.add(task)
            for dep_name in task.depends:
                queue.append(dep_name)

        # Build initial task states and the reverse dependency mapping.
        task_states: dict[Task, TaskState] = {}
        reverse_dependencies: dict[str, set[Task]] = defaultdict(lambda: set())
        for task in all_tasks:
            task_states[task] = TaskState.create(task)
            for dep_name in task.depends:
                reverse_dependencies[dep_name].add(task)

        return (len(all_tasks), task_states, reverse_dependencies)

    def __do_ready_tasks(
        self,
        progress_bar: tqdm,  # type: ignore
        executor: Executor,
        task_states: dict[Task, TaskState],
        reverse_dependencies: dict[str, set[Task]],
        future_dict: dict[Future[None], Task],
        force: bool = False,
    ) -> None:
        """
        Identifies and submits ready tasks to the executor.

        A task is "ready" if it is in the PENDING state and all its
        dependencies have been met.

        Parameters
        ----------
        progress_bar : tqdm
            The progress bar instance to update.
        executor : Executor
            The thread or process pool executor to submit tasks to.
        task_states : dict[Task, TaskState]
            The current state of all tasks.
        reverse_dependencies : dict[str, set[Task]]
            The reverse dependency graph.
        future_dict : dict[Future[None], Task]
            A dictionary to store the future objects of submitted tasks.
        force : bool
            If True, run the task even if `should_run()` is False.
        """

        for task, state in task_states.items():
            if not state.is_ready:
                continue

            if force or task.should_run():
                # Submit the task for execution.
                task_states[task].status = RunStatus.RUNNING
                future = executor.submit(task.execute)
                future_dict[future] = task

            else:
                # The task doesn't need to run, so mark it as skipped.
                self.__mark_task_completed(
                    progress_bar,
                    task_states,
                    reverse_dependencies,
                    task,
                    RunStatus.SKIPPED,
                )

    def __mark_task_completed(
        self,
        progress_bar: tqdm,  # type: ignore
        task_states: dict[Task, TaskState],
        reverse_dependencies: dict[str, set[Task]],
        task: Task,
        status: RunStatus,
    ) -> None:
        """
        Marks a task as finished and updates the state of its dependents.

        This method is thread-safe.

        Parameters
        ----------
        progress_bar : tqdm
            The progress bar instance to update.
        task_states : dict[Task, TaskState]
            The current state of all tasks.
        reverse_dependencies : dict[str, set[Task]]
            The reverse dependency graph.
        task : Task
            The task that has just finished.
        status : RunStatus
            The new status of the task (COMPLETED, SKIPPED, or FAILED).
        """

        # Avoid processing the same task completion multiple times.
        if task_states[task].is_finished:  # pragma: no cover
            return

        # Update the task's status and advance the progress bar.
        task_states[task].status = status
        progress_bar.update(1)

        # If the task was successful or skipped, decrement the dependency
        # counter for all tasks that depend on it.
        if status in [RunStatus.COMPLETED, RunStatus.SKIPPED]:
            for dependent_task in reverse_dependencies[task.name]:
                if task_states[dependent_task].status == RunStatus.PENDING:
                    task_states[dependent_task].remaining_dependencies_count.countdown()

        # If the task failed, we must propagate this failure to all
        # downstream tasks that depend on it.
        if status == RunStatus.FAILED:
            for dependent_task in reverse_dependencies[task.name]:
                # Recursively call this function to mark the dependent as FAILED
                # and continue the failure cascade.
                self.__mark_task_completed(
                    progress_bar,
                    task_states,
                    reverse_dependencies,
                    dependent_task,
                    RunStatus.FAILED,
                )
