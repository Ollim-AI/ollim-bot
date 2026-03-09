"""Skill permission helpers for bg fork dispatch.

Skills are loaded by the SDK via setting_sources=["project"] + the Skill tool.
This module only provides helpers for adding Skill tool patterns to bg fork
allowed_tools — the SDK handles skill content loading and allowed-tools
enforcement natively (before our can_use_tool callback).
"""
