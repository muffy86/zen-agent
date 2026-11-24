"""zen-agent — polyglot agentic runtime (python head).

Same protocol, same golden vectors, same decisions as the TypeScript and Kotlin heads.
"""
from .agent import complete, run_live_loop, run_scripted_loop
from .memory import MemoryStore
from .policy import evaluate, load_rules
from .router import assertable_view, infer_capability, load_registry, route
from .tools import calc, run_tool

__version__ = "1.0.0"

__all__ = [
    "complete",
    "run_live_loop",
    "run_scripted_loop",
    "MemoryStore",
    "evaluate",
    "load_rules",
    "assertable_view",
    "infer_capability",
    "load_registry",
    "route",
    "calc",
    "run_tool",
]
