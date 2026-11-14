"""mycal: data model and scheduling solver."""

from mycal.model import (
    Block,
    BlockStatus,
    Constraint,
    FlexPreset,
    Item,
    ItemTemplate,
    OnMiss,
    Rule,
    Series,
    Window,
    WorkFrame,
)
from mycal.presets import compile_constraint, compile_windows
from mycal.settings import SolverSettings
from mycal.solve import SolveResult, solve
from mycal.windows import work_frame_windows

__all__ = [
    "Block",
    "BlockStatus",
    "Constraint",
    "FlexPreset",
    "Item",
    "ItemTemplate",
    "OnMiss",
    "Rule",
    "Series",
    "SolveResult",
    "SolverSettings",
    "Window",
    "WorkFrame",
    "compile_constraint",
    "compile_windows",
    "solve",
    "work_frame_windows",
]
