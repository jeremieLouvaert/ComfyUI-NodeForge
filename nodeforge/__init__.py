"""NodeForge v0.1 -- the AUTHOR branch.

A CLI agent that takes a vague natural-language ask, authors a custom ComfyUI
node, self-verifies it through the escalating-oracle pipeline (docs/
self-verification-model.md), and -- only on human approval -- banks it into a
live ComfyUI install.

Architecture rule: the parent/agent process never imports torch and never execs
candidate code. Everything torch-touching or candidate-executing runs only in
the sandbox child subprocess (sandbox.py + _child.py).
"""
