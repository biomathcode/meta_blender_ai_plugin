"""Material construction and the Muse Geometry Nodes group.

Geometry Nodes cannot call HTTP, so generation stays in operators; the
groups built here *consume* the generated image:

* Shader side  - a per-material node tree (TexCoord > Mapping > Image
  Texture > Principled, plus derived Bump / Roughness from the same image).
  Shader Image Texture nodes take their image from a property, not a
  socket, so this is built per material instead of as a shared group.
* Geometry side - a reusable ``Muse GN Texture`` node group with a real
  Image socket: it samples the generated texture by position, stores it as
  a ``muse_height`` attribute, displaces along normals and sets a material.
"""

from __future__ import annotations

import bpy

GN_GROUP_NAME = "Muse GN Texture"
GN_VERSION = 1


# ---------------------------------------------------------------------------
# Shader / material
# ---------------------------------------------------------------------------

def _link(links, from_node, from_socket, to_node, to_socket):
    links.new(from_node.outputs[from_socket], to_node.inputs[to_socket])


def apply_image_to_material(material, image, use_bump=True, use_roughness=True,
                            texture_scale=1.0):
    """(Re)build `material` as a Muse PBR material using `image`."""
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()

    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (520, 0)
    principled = tree.nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (280, 0)
    _link(tree.links, principled, "BSDF", output, "Surface")

    texcoord = tree.nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-760, 0)
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.location = (-580, 0)
    mapping.inputs["Scale"].default_value = (texture_scale, texture_scale, texture_scale)
    _link(tree.links, texcoord, "UV", mapping, "Vector")

    tex_color = tree.nodes.new("ShaderNodeTexImage")
    tex_color.name = tex_color.label = "Muse Texture (Color)"
    tex_color.location = (-360, 120)
    tex_color.image = image
    tex_color.image.colorspace_settings.name = "sRGB"
    _link(tree.links, mapping, "Vector", tex_color, "Vector")
    if "Base Color" in principled.inputs:
        _link(tree.links, tex_color, "Color", principled, "Base Color")

    if use_bump or use_roughness:
        tex_data = tree.nodes.new("ShaderNodeTexImage")
        tex_data.name = tex_data.label = "Muse Texture (Data)"
        tex_data.location = (-360, -220)
        tex_data.image = image.copy()  # colorspace is per-image: keep sRGB copy apart
        tex_data.image.colorspace_settings.name = "Non-Color"
        _link(tree.links, mapping, "Vector", tex_data, "Vector")
        if use_bump and "Normal" in principled.inputs:
            bump = tree.nodes.new("ShaderNodeBump")
            bump.location = (40, -240)
            bump.inputs["Strength"].default_value = 0.35
            bump.inputs["Distance"].default_value = 0.02
            _link(tree.links, tex_data, "Color", bump, "Height")
            _link(tree.links, bump, "Normal", principled, "Normal")
        if use_roughness and "Roughness" in principled.inputs:
            ramp = tree.nodes.new("ShaderNodeMapRange")
            ramp.location = (40, -60)
            ramp.inputs["From Min"].default_value = 0.0
            ramp.inputs["From Max"].default_value = 1.0
            ramp.inputs["To Min"].default_value = 0.35
            ramp.inputs["To Max"].default_value = 0.9
            _link(tree.links, tex_data, "Color", ramp, "Value")
            _link(tree.links, ramp, "Result", principled, "Roughness")
    return material


def apply_image_to_object(obj, image, use_bump=True, use_roughness=True,
                          texture_scale=1.0, material_name=""):
    """Create (or reuse) a Muse material on `obj` and make it active."""
    name = material_name or f"Muse_{image.name}"[:63]
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    apply_image_to_material(material, image, use_bump, use_roughness, texture_scale)
    if obj.data.materials:
        obj.data.materials[0] = material
    else:
        obj.data.materials.append(material)
    obj.active_material = material
    return material


# ---------------------------------------------------------------------------
# Geometry Nodes group
# ---------------------------------------------------------------------------

def _socket(tree, name, in_out, socket_type, default=None):
    sock = tree.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    if default is not None and hasattr(sock, "default_value"):
        try:
            sock.default_value = default
        except (TypeError, ValueError):
            pass
    return sock


def ensure_gn_group():
    """Create the Muse GN Texture group once; reuse it afterwards."""
    group = bpy.data.node_groups.get(GN_GROUP_NAME)
    if group and group.get("muse_ai_version") == GN_VERSION:
        return group
    if group:
        bpy.data.node_groups.remove(group)
    group = bpy.data.node_groups.new(GN_GROUP_NAME, "GeometryNodeTree")
    group["muse_ai_version"] = GN_VERSION
    group.interface.new_socket(name="Geometry", in_out="OUTPUT",
                               socket_type="NodeSocketGeometry")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Image", "INPUT", "NodeSocketImage")
    _socket(group, "Strength", "INPUT", "NodeSocketFloat", 0.08)
    _socket(group, "Texture Scale", "INPUT", "NodeSocketFloat", 1.0)
    _socket(group, "Material", "INPUT", "NodeSocketMaterial")

    nodes, links = group.nodes, group.links
    group_in = nodes.new("NodeGroupInput")
    group_in.location = (-900, 0)
    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (700, 0)

    position = nodes.new("GeometryNodeInputPosition")
    position.location = (-900, -260)
    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.location = (-720, -340)
    scale_pos = nodes.new("ShaderNodeVectorMath")
    scale_pos.operation = "MULTIPLY"
    scale_pos.location = (-540, -260)

    image_tex = nodes.new("GeometryNodeImageTexture")
    image_tex.location = (-320, -160)
    image_tex.interpolation = "Linear"
    # FunctionNode* in Geometry Nodes trees (ShaderNode* is rejected there).
    separate = nodes.new("FunctionNodeSeparateColor")
    separate.location = (-120, -160)

    normal = nodes.new("GeometryNodeInputNormal")
    normal.location = (-320, -420)
    centered = nodes.new("ShaderNodeMath")
    centered.operation = "SUBTRACT"
    centered.location = (60, -160)
    centered.inputs[1].default_value = 0.5
    scaled = nodes.new("ShaderNodeMath")
    scaled.operation = "MULTIPLY"
    scaled.location = (240, -160)
    offset = nodes.new("ShaderNodeVectorMath")
    offset.operation = "SCALE"
    offset.location = (420, -260)

    store = nodes.new("GeometryNodeStoreNamedAttribute")
    store.data_type = "FLOAT"
    store.domain = "POINT"
    store.inputs["Name"].default_value = "muse_height"
    store.location = (-120, 120)
    set_pos = nodes.new("GeometryNodeSetPosition")
    set_pos.location = (180, 120)
    set_mat = nodes.new("GeometryNodeSetMaterial")
    set_mat.location = (420, 120)

    def link(a, a_sock, b, b_sock):
        links.new(a.outputs[a_sock], b.inputs[b_sock])

    link(group_in, "Texture Scale", combine, "X")
    link(group_in, "Texture Scale", combine, "Y")
    link(group_in, "Texture Scale", combine, "Z")
    link(position, "Position", scale_pos, 0)
    link(combine, "Vector", scale_pos, 1)
    link(scale_pos, "Vector", image_tex, "Vector")
    link(group_in, "Image", image_tex, "Image")
    link(image_tex, "Color", separate, "Color")
    link(separate, "Green", centered, 0)
    link(centered, "Value", scaled, 0)
    link(group_in, "Strength", scaled, 1)
    link(normal, "Normal", offset, 0)
    link(scaled, "Value", offset, "Scale")
    link(group_in, "Geometry", store, "Geometry")
    link(separate, "Green", store, "Value")
    link(store, "Geometry", set_pos, "Geometry")
    link(offset, "Vector", set_pos, "Offset")
    link(set_pos, "Geometry", set_mat, "Geometry")
    link(group_in, "Material", set_mat, "Material")
    link(set_mat, "Geometry", group_out, "Geometry")
    return group


def _set_modifier_input(modifier, group, socket_name, value):
    for item in group.interface.items_tree:
        if (getattr(item, "item_type", "") == "SOCKET"
                and getattr(item, "in_out", "") == "INPUT"
                and item.name == socket_name):
            # Blender 5.x: modifier.properties.inputs.<identifier>.value
            try:
                inputs = modifier.properties.inputs
                entry = getattr(inputs, item.identifier, None)
                if entry is not None and hasattr(entry, "value"):
                    entry.value = value
                    return
            except (TypeError, AttributeError, RuntimeError):
                pass
            # Blender <= 4.x: ID-property style modifier["Input_N"]
            try:
                modifier[item.identifier] = value
            except (TypeError, KeyError, RuntimeError):
                pass
            return


def add_gn_modifier(obj, image=None, strength=0.08, texture_scale=1.0, material=None):
    """Add (or reuse) the Muse Geometry Nodes modifier on `obj`."""
    group = ensure_gn_group()
    modifier = next((m for m in obj.modifiers
                     if m.type == "NODES" and m.node_group == group), None)
    if modifier is None:
        modifier = obj.modifiers.new("Muse Harness", "NODES")
        modifier.node_group = group
    if image is not None:
        _set_modifier_input(modifier, group, "Image", image)
    _set_modifier_input(modifier, group, "Strength", float(strength))
    _set_modifier_input(modifier, group, "Texture Scale", float(texture_scale))
    if material is not None:
        _set_modifier_input(modifier, group, "Material", material)
    return modifier


def set_gn_image(obj, image):
    """Point an existing Muse GN modifier at `image`. Returns the modifier."""
    group = bpy.data.node_groups.get(GN_GROUP_NAME)
    if group is None:
        return None
    for modifier in obj.modifiers:
        if modifier.type == "NODES" and modifier.node_group == group:
            _set_modifier_input(modifier, group, "Image", image)
            return modifier
    return None
