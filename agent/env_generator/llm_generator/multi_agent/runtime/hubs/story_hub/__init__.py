"""StoryHub JsonStore handles.

Byte-for-byte mirror of RunHubStores / WorkHubStores patterns. Owns
the ``stories`` table that ``story_hub.register_story`` persists into
when the StoryHub class is wired with stores via hub_registry.
"""

from .stores import StoryHubStores  # noqa: F401

__all__ = ["StoryHubStores"]
