"""Facade for parallel subtask execution support."""

from .parallel_runtime import (
    ParallelContractSupport,
    ParallelCoordinationSupport,
    ParallelMetricsSupport,
    ProfiledParallelExecutionSupport,
    StandardParallelExecutionSupport,
)


class ParallelExecutionSupport(
    ParallelMetricsSupport,
    ParallelContractSupport,
    ParallelCoordinationSupport,
    StandardParallelExecutionSupport,
    ProfiledParallelExecutionSupport,
):
    """Backward-compatible parallel execution facade."""

    pass


__all__ = ["ParallelExecutionSupport"]
