"""MoR's own engine — the machinery under the Hall.

Not a wrapper around Hermes: MoR is the standard, and the best of the Hermes
harness is cut down and carried in here, rewritten to the realm's idiom. A face
in the Hall thinks and acts through this engine — a real model backend, a real
tool loop, and the hard-won reflexes (reflect when acting without thinking,
taint what comes from outside) that made the old harness trustworthy.
"""

from mor.engine.backend import (Backend, ChatResult, MockBackend, ScriptBackend,
                                 ServedBackend, ToolCall, flavored_line, make_backend)
from mor.engine.compaction import hall_view
from mor.engine.dome import Dome, probe_runtime
from mor.engine.loop import think_and_act
from mor.engine.tools import Tool, ToolContext, default_tools

__all__ = [
    "Backend", "ServedBackend", "MockBackend", "ScriptBackend", "ChatResult",
    "ToolCall", "flavored_line", "make_backend",
    "Tool", "ToolContext", "default_tools", "think_and_act",
    "Dome", "probe_runtime", "hall_view",
]
