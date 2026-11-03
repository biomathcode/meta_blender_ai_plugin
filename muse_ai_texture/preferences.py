"""Addon Preferences: API key override, endpoints, storage.

The normal setup is a `.env` file with META_API_KEY (see README). The fields
here override it — handy when Blender is launched away from the project.
"""

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import AddonPreferences

from . import api_client, modal_client


class MuseAddonPreferences(AddonPreferences):
    bl_idname = __package__

    api_key: StringProperty(
        name="Meta API Key (override)",
        description="Optional. Overrides META_API_KEY from the environment / .env",
        default="", subtype="PASSWORD",
    )
    env_file: StringProperty(
        name=".env File",
        description="Optional explicit path to a .env file holding META_API_KEY",
        default="", subtype="FILE_PATH",
    )
    base_url: StringProperty(name="Base URL", default=api_client.DEFAULT_BASE_URL)
    model: StringProperty(name="Image Model", default=api_client.DEFAULT_MODEL)
    output_dir: StringProperty(
        name="Textures Folder",
        description="Where generated textures are saved (blank = next to the "
                    ".blend, or the addon 'generated' folder)",
        default="", subtype="DIR_PATH",
    )
    timeout: IntProperty(name="Timeout (s)", default=300, min=30, max=900)
    modal_token_id: StringProperty(
        name="Modal Token ID (override)",
        description="Optional. Overrides MODAL_TOKEN_ID from the environment / .env",
        default="", subtype="PASSWORD",
    )
    modal_token_secret: StringProperty(
        name="Modal Token Secret (override)",
        description="Optional. Overrides MODAL_TOKEN_SECRET from the environment / .env",
        default="", subtype="PASSWORD",
    )
    modal_cli_path: StringProperty(
        name="Modal CLI Path",
        description="Optional explicit path to the `modal` executable "
                    "(blank = find it on PATH)",
        default="", subtype="FILE_PATH",
    )
    modal_app_name: StringProperty(
        name="Modal App Name", default=modal_client.DEFAULT_APP_NAME)
    splat_python: StringProperty(
        name="Splat Worker Python (override)",
        description="Optional explicit Python for the SAM 3.1 splat worker "
                    "(blank = project .venv-splat from Create Worker Env, "
                    "then python3.11/python3 on PATH). The worker only "
                    "renders views and votes; SAM 3.1 runs on the Meta API",
        default="", subtype="FILE_PATH")

    def draw(self, context):
        layout = self.layout
        from . import utils
        _key, source, _url, _model = utils.api_settings(context)
        box = layout.box()
        box.label(text="Meta Muse Image — connection", icon=utils.safe_icon("KEYINGSET"))
        row = box.row()
        row.label(text=f"Key source: {source}", icon=utils.safe_icon("CHECKMARK" if _key else "ERROR"))
        box.prop(self, "api_key")
        box.prop(self, "env_file")
        box.label(text="Leave the key blank to use META_API_KEY from a .env file "
                       "(addon folder, .blend folder, or the path above).")
        row = box.row(align=True)
        row.operator("muse.test_connection", icon=utils.safe_icon("URL"))
        row.operator("wm.url_open", text="Get a key (dev.meta.ai)", icon=utils.safe_icon("WORLD")).url = \
            "https://dev.meta.ai"
        box = layout.box()
        box.label(text="Model API", icon=utils.safe_icon("IMAGE_DATA"))
        box.prop(self, "base_url")
        box.prop(self, "model")
        box.prop(self, "output_dir")
        box.prop(self, "timeout")
        creds = utils.modal_settings(context)[0]
        cli = utils.modal_settings(context)[2]
        box = layout.box()
        box.label(text="Cloud Render — Modal (camera viewport)", icon=utils.safe_icon("RENDER_STILL"))
        row = box.row()
        row.label(text=f"Modal tokens: {creds.source}",
                  icon=utils.safe_icon("CHECKMARK" if creds.ok else "ERROR"))
        box.prop(self, "modal_token_id")
        box.prop(self, "modal_token_secret")
        box.label(text="Leave both blank to use MODAL_TOKEN_ID / "
                       "MODAL_TOKEN_SECRET from a .env file or the environment.")
        box.prop(self, "modal_cli_path")
        box.prop(self, "modal_app_name")
        row = box.row()
        row.label(text=f"Modal CLI: {cli or 'not found — pip install modal'}",
                  icon=utils.safe_icon("CHECKMARK" if cli else "ERROR"))
        row = box.row(align=True)
        row.operator("muse.cloud_test", icon=utils.safe_icon("URL"))
        row.operator("wm.url_open", text="Get tokens (modal.com)", icon=utils.safe_icon("WORLD")).url = \
            "https://modal.com/settings/tokens"
        box = layout.box()
        box.label(text="Gaussian Splat — SAM 3.1 (Meta Model API)", icon=utils.safe_icon("POINTCLOUD_DATA"))
        box.prop(self, "splat_python")
        box.label(text="SAM 3.1 (sam-3.1) runs on the Meta Model API with the")
        box.label(text="same Meta key above — no extra token, no weights download.")
        box.label(text="The worker only renders views and votes masks onto points.")
        box.label(text="Use Create Worker Env in the splat panel for one-click setup.")
        row = box.row(align=True)
        row.operator("muse.splat_check_setup", icon=utils.safe_icon("URL"))
        row.operator("muse.splat_setup_worker", icon=utils.safe_icon("ADD"))


classes = (MuseAddonPreferences,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
