"""
File Diff Utilities
===================

Generate unified and structured diffs for file changes.
"""

from __future__ import annotations

from typing import Dict, List
import difflib


def generate_unified_diff(old_content: str, new_content: str, file_path: str) -> str:
    old_lines = _split_lines(old_content)
    new_lines = _split_lines(new_content)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm="",
    )
    return "".join(diff)


def generate_git_diff(old_content: str, new_content: str, file_path: str) -> str:
    unified = generate_unified_diff(old_content, new_content, file_path)
    if not unified:
        return ""
    header = f"diff --git a/{file_path} b/{file_path}\n"
    return header + unified


def build_structured_diff(old_content: str, new_content: str) -> List[Dict[str, object]]:
    old_lines = _split_lines(old_content)
    new_lines = _split_lines(new_content)
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    hunks: List[Dict[str, object]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks.append({
            "tag": tag,
            "old_start": i1,
            "old_end": i2,
            "new_start": j1,
            "new_end": j2,
            "old_lines": old_lines[i1:i2],
            "new_lines": new_lines[j1:j2],
        })
    return hunks


def _split_lines(content: str) -> List[str]:
    return content.splitlines(keepends=True)
