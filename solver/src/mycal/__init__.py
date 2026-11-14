"""mycal: data model and scheduling solver."""

from mycal.model import (
    Block,
    BlockStatus,
    Constraint,
    FlexPreset,
    Item,
    OnMiss,
    Window,
    WorkFrame,
)
from mycal.solve import SolveResult, SolverSettings, solve
from mycal.windows import work_frame_windows

__all__ = [
    "Block",
    "BlockStatus",
    "Constraint",
    "FlexPreset",
    "Item",
    "OnMiss",
    "SolveResult",
    "SolverSettings",
    "Window",
    "WorkFrame",
    "solve",
    "work_frame_windows",
]
