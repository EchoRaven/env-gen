"""Structured collaboration hubs for multi-agent coordination.

Currently the ``hubs/`` package only holds the modular CodeHub and WorkHub
implementations. RegistryHub and EventHub still live at the parent ``runtime/``
level (``runtime/registryhub.py`` / ``runtime/eventhub.py``) and are imported
directly by ``runtime/hub_workspace.py``.
"""

from .codehub import CodeHub
from .workhub import WorkHub

__all__ = ["CodeHub", "WorkHub"]
