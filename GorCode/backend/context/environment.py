"""
System Environment Prompt Block
================================

Builds the standardized Environment block appended to system prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class EnvironmentBlockInputs:
    """Input values for the Environment prompt block."""

    primary_workdir: str
    is_git_repo: bool
    additional_workdirs: List[str]
    platform: str
    shell: str
    os_version: str


def build_environment_block(inputs: EnvironmentBlockInputs) -> str:
    """Build the Environment block string from structured inputs."""
    additional = _format_additional_workdirs(inputs.additional_workdirs)
    git_value = "yes" if inputs.is_git_repo else "no"

    lines = [
        "# Environment",
        "",
        "You have been invoked in the following environment:",
        "",
        f"- Primary working directory: {inputs.primary_workdir}",
        f"- Is a git repository: {git_value}",
        f"- Additional working directories: {additional}",
        f"- Platform: {inputs.platform}",
        f"- Shell: {inputs.shell}",
        f"- OS Version: {inputs.os_version}",
    ]
    return "\n".join(lines)


def _format_additional_workdirs(additional_workdirs: Optional[Iterable[str]]) -> str:
    """Format additional working directories for the Environment block."""
    if not additional_workdirs:
        return "None"

    return ", ".join(str(value) for value in additional_workdirs)
