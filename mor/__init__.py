"""MoRE — a small, honest multi-agent CLI harness for local LLMs.

A crew of agents shares one workspace and one transcript, takes turns by
addressing each other by name, uses real sandboxed tools (files, an opt-in host
shell, and a single gated web egress), and you steer from the top. It runs on the
Python standard library — nothing to install — against any OpenAI-compatible
model endpoint, and on a built-in offline stand-in when none is attached.

See the README for the design and the mapping from the earlier, more elaborate
version this replaced.
"""

__version__ = "1.0.0"

from mor.cli import main

__all__ = ["main"]
