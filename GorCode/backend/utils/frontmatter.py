"""
Frontmatter parsing helpers.
"""

import re
from typing import Any, Dict, Tuple

import yaml


_YAML_FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)$",
    re.DOTALL,
)


def parse_yaml_frontmatter(
    content: str,
    *,
    strip_on_error: bool,
) -> Tuple[Dict[str, Any], str, bool]:
    """
    Parse YAML frontmatter from Markdown content.

    Args:
        content: Raw Markdown content
        strip_on_error: When True, strip the frontmatter block even if YAML is invalid

    Returns:
        Tuple of (frontmatter_dict, remaining_content, has_frontmatter)
    """
    match = _YAML_FRONTMATTER_PATTERN.match(content)
    if not match:
        return {}, content, False

    yaml_content = match.group(1)
    remaining_content = match.group(2)

    try:
        frontmatter = yaml.safe_load(yaml_content) or {}
        return frontmatter, remaining_content, True
    except yaml.YAMLError:
        if strip_on_error:
            return {}, remaining_content, True
        return {}, content, False
