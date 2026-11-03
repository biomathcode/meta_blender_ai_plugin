"""Muse Harness — Meta Muse Image 1.0 textures + Geometry Nodes for Blender.

Like the ComfyUI-BlenderAI-node workflow, but Meta Muse only:
prompt -> Muse Image 1.0 (Meta Model API) -> texture on your material,
with a Geometry Nodes group that consumes the same generated image.

API key: META_API_KEY in a .env file (addon folder, .blend folder, or the
path set in Addon Preferences) or pasted in Addon Preferences.
"""

bl_info = {
    "name": "Muse Harness",
    "author": "Muse Harness",
    "version": (1, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Muse Harness | Shader / Geometry Nodes editors",
    "description": "Generate textures with Meta Muse Image 1.0 and drive "
                   "materials + Geometry Nodes with them",
    "category": "Material",
}

from . import (  # noqa: E402
    chat_operators,
    cloud_operators,
    operators,
    panels,
    preferences,
    properties,
    showcase_operators,
    splat_operators,
)


def register():
    preferences.register()
    properties.register()
    operators.register()
    chat_operators.register()
    cloud_operators.register()
    showcase_operators.register()
    splat_operators.register()
    panels.register()


def unregister():
    panels.unregister()
    splat_operators.unregister()
    showcase_operators.unregister()
    cloud_operators.unregister()
    chat_operators.unregister()
    operators.unregister()
    properties.unregister()
    preferences.unregister()


if __name__ == "__main__":
    register()
