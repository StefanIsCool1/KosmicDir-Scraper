"""Phase 0 — Source Discovery & Intelligent Routing.

Sits before Phase 1 (Bot/) and Phase 2 (Phase2Bot/). Takes a free-form user
goal, finds candidate sources, qualifies them, and classifies each as
DIRECTORY (→ Phase 1) or WEBSITE (→ Phase 2). Phase 1 and Phase 2 are not
modified — Phase 0 only feeds them.
"""
from .pipeline import run_discovery
from .intent import parse_intent

__all__ = ["run_discovery", "parse_intent"]
