"""aitask — cross-AI-tool dev workflow integration for AiCodeTask.

Public API:
    from aitask import AiTaskClient, load_config, build_task_description
"""
from .client import AiTaskClient
from .config import load_config, AiTaskConfig
from .tags import build_task_description, LINK_TAGS

__all__ = [
    "AiTaskClient",
    "AiTaskConfig",
    "load_config",
    "build_task_description",
    "LINK_TAGS",
]
__version__ = "0.1.0"
