"""Agent prompts for the multi-agent system."""

from .agent2_prompts import (
    AGENT2_SYSTEM_PROMPT,
    AGENT2_VALIDATION_PROMPT,
    AGENT2_NORMALIZATION_PROMPT,
    AGENT2_FEASIBILITY_PROMPT,
    AGENT2_DEDUPLICATION_PROMPT,
    AGENT2_DESIGN_PROMPT,
    get_agent2_full_analysis_prompt,
)

__all__ = [
    "AGENT2_SYSTEM_PROMPT",
    "AGENT2_VALIDATION_PROMPT",
    "AGENT2_NORMALIZATION_PROMPT",
    "AGENT2_FEASIBILITY_PROMPT",
    "AGENT2_DEDUPLICATION_PROMPT",
    "AGENT2_DESIGN_PROMPT",
    "get_agent2_full_analysis_prompt",
]
