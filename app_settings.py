"""
Runtime settings shared by the desktop shell and engine bootstrap.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_LLM_URL = "http://localhost:11434"
DEFAULT_LLM_MODEL = "qwen2.5:7b"
DEFAULT_DB_PATH = "memory.db"


@dataclass(slots=True)
class AppSettings:
    llm_url: str = DEFAULT_LLM_URL
    llm_model: str = DEFAULT_LLM_MODEL
    db_path: str = DEFAULT_DB_PATH

    @classmethod
    def from_sources(
        cls,
        llm_url: str | None = None,
        llm_model: str | None = None,
        db_path: str | None = None,
    ) -> "AppSettings":
        return cls(
            llm_url=llm_url or os.getenv("WINAI_LLM_URL") or os.getenv("OLLAMA_HOST") or DEFAULT_LLM_URL,
            llm_model=llm_model or os.getenv("WINAI_LLM_MODEL") or DEFAULT_LLM_MODEL,
            db_path=db_path or os.getenv("WINAI_DB_PATH") or DEFAULT_DB_PATH,
        )