"""
Init Result Rendering
=====================

Shared helpers for rendering init command results.
"""

from typing import Union

from GorCode.shared.types import InitResult
from GorCode.frontend.ui.renderer import UIRenderer


def _coerce_init_result(result: Union[InitResult, dict]) -> InitResult:
    if isinstance(result, InitResult):
        return result
    if isinstance(result, dict):
        return InitResult.from_dict(result)
    return InitResult(success=False, message="Invalid init result")


def render_init_result(ui_renderer: UIRenderer, name: str, result: Union[InitResult, dict]) -> None:
    """Render initialization result with a shared layout."""
    result = _coerce_init_result(result)
    if result.success:
        ui_renderer.print_success(f"{name} configuration: {result.message}")
        if result.created_paths:
            ui_renderer.print("  Created:", style="dim")
            for path in result.created_paths:
                ui_renderer.print(f"    • {path}", style="dim")
    else:
        ui_renderer.print_error(f"{name} configuration: {result.message}")
        for error in result.errors:
            ui_renderer.print(f"  Error: {error}", style="dim")
