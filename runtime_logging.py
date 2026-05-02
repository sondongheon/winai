"""
Small logging helper for toggling noisy engine prints.
"""

from __future__ import annotations


def debug_log(enabled: bool, message: str):
    if enabled:
        print(message)