# SPDX-License-Identifier: GPL-2.0-or-later
"""Color Correct (MaterialX) — a Blender add-on (extension).

Recreates the MaterialX ``colorcorrect`` compound node (``NG_colorcorrect_color3``
from the MaterialX standard library ``stdlib_ng.mtlx``) as a shader Node Group
built entirely from Blender's built-in shader nodes (Math / Vector Math / Mix /
Separate & Combine Color, etc.).

This is useful when authoring materials in Blender that need to match a look
developed in MaterialX-based pipelines (Houdini/Solaris, Karma, etc.), where
``colorcorrect`` is a common grading node that has no direct Blender equivalent.

This is an independent, unofficial recreation of the node's published formula.
It contains no code from the MaterialX project and is not affiliated with or
endorsed by the MaterialX project or the Academy Software Foundation.

Usage:
    Shader Editor > Add > Group > Color Correct (MaterialX)

The node group exposes the same inputs as the MaterialX node:
    In, Hue, Saturation, Gamma, Lift, Gain, Contrast, Contrast Pivot, Exposure

Implementation notes:
    A single shared Node Group (named "Color Correct (MaterialX)") is created
    on first use and reused afterwards, so adding the node to many materials
    does not duplicate the ~30 internal nodes each time. The group is
    identified by a custom property marker rather than by name, so it never
    collides with same-named groups created by other tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import bpy

# Name of the shared node group datablock. Kept stable so repeated use (and
# other tools that build the same group) reuse one definition instead of
# accumulating duplicates.
GROUP_NAME = "Color Correct (MaterialX)"

# Marker custom property identifying groups created by this add-on. Groups
# are looked up by this marker rather than by name, so a node group that some
# other tool (e.g. a future official MaterialX integration) happens to create
# with the same name is never mistaken for ours, and vice versa.
GROUP_MARKER = "color_correct_materialx"

# Interface definition: (MaterialX input name, UI label, socket type)
INPUT_SOCKETS: tuple[tuple[str, str, str], ...] = (
    ("in", "In", "NodeSocketColor"),
    ("hue", "Hue", "NodeSocketFloat"),
    ("saturation", "Saturation", "NodeSocketFloat"),
    ("gamma", "Gamma", "NodeSocketFloat"),
    ("lift", "Lift", "NodeSocketFloat"),
    ("gain", "Gain", "NodeSocketFloat"),
    ("contrast", "Contrast", "NodeSocketFloat"),
    ("contrastpivot", "Contrast Pivot", "NodeSocketFloat"),
    ("exposure", "Exposure", "NodeSocketFloat"),
)

# Default luminance coefficients used by MaterialX (ACEScg primaries).
_LUMA_COEFFS_ACESCG = (0.2722287, 0.6740818, 0.0536895)


@dataclass
class _Resolved:
    """Result of evaluating an expression term.

    Either a node output socket (``socket``) or an unconnected constant
    (``value``); ``kind`` records the MaterialX-style type ("float",
    "color3", "vector3") for broadcast decisions.
    """

    kind: str
    socket: Any = None
    value: Any = None


def _place(node: Any, cursor: dict[str, float], depth: int) -> Any:
    """Set a rough visual layout position (deeper recursion goes further left)."""
    node.location = (-500.0 - depth * 220.0, cursor["y"])
    cursor["y"] -= 180.0
    return node


def _coerce_value(value: Any, socket_type: str) -> Any:
    """Convert a constant into the ``default_value`` shape a socket expects."""
    if socket_type == "VALUE":
        if isinstance(value, (list, tuple)):
            return float(value[0])
        return float(value)
    seq = list(value) if isinstance(value, (list, tuple)) else [float(value)] * 3
    while len(seq) < 3:
        seq.append(0.0)
    if socket_type == "RGBA":
        return (*[float(c) for c in seq[:3]], 1.0)
    return tuple(float(c) for c in seq[:3])


def _assign(links: Any, input_socket: Any, resolved: _Resolved) -> None:
    """Connect a resolved term to an input socket, or set its default value."""
    if resolved.socket is not None:
        links.new(resolved.socket, input_socket)
    else:
        input_socket.default_value = _coerce_value(resolved.value, input_socket.type)


def _broadcast_to_color(
    nodes: Any, links: Any, value: _Resolved, cursor: dict[str, float], depth: int,
) -> _Resolved:
    """Broadcast a float term to color3 (pass through if already color3)."""
    if value.kind != "float":
        return value
    node = _place(nodes.new("ShaderNodeCombineColor"), cursor, depth)
    for i in range(3):
        _assign(links, node.inputs[i], value)
    return _Resolved(kind="color3", socket=node.outputs["Color"])


def _vecmath(
    nodes: Any, links: Any, operation: str, a: _Resolved, b: "_Resolved | None",
    cursor: dict[str, float], depth: int, kind: str = "color3",
) -> _Resolved:
    """Build one Vector Math node from already-resolved operands.

    Scalar-output operations (DOT_PRODUCT / LENGTH / DISTANCE) use the
    "Value" output instead of "Vector".
    """
    node = _place(nodes.new("ShaderNodeVectorMath"), cursor, depth)
    node.operation = operation
    _assign(links, node.inputs[0], a)
    if b is not None:
        _assign(links, node.inputs[1], b)
    output_name = "Value" if operation in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else "Vector"
    return _Resolved(kind=kind, socket=node.outputs[output_name])


def _mathop(
    nodes: Any, links: Any, operation: str, a: _Resolved, b: "_Resolved | None",
    cursor: dict[str, float], depth: int,
) -> _Resolved:
    """Build one (scalar) Math node from already-resolved operands."""
    node = _place(nodes.new("ShaderNodeMath"), cursor, depth)
    node.operation = operation
    _assign(links, node.inputs[0], a)
    if b is not None:
        _assign(links, node.inputs[1], b)
    return _Resolved(kind="float", socket=node.outputs["Value"])


def _vec_power(
    nodes: Any, links: Any, base: _Resolved, exponent: _Resolved,
    cursor: dict[str, float], depth: int,
) -> _Resolved:
    """Per-channel color power: base ^ exponent (exponent is a float term).

    Built from Separate Color + three scalar Math POWER nodes + Combine
    Color, because the Vector Math node only gained a POWER operation in
    Blender 5.0 and this add-on supports 4.2 onwards.
    """
    sep = _place(nodes.new("ShaderNodeSeparateColor"), cursor, depth)
    _assign(links, sep.inputs[0], base)
    comb = _place(nodes.new("ShaderNodeCombineColor"), cursor, depth)
    for i in range(3):
        powered = _mathop(
            nodes, links, "POWER",
            _Resolved(kind="float", socket=sep.outputs[i]), exponent,
            cursor, depth,
        )
        links.new(powered.socket, comb.inputs[i])
    return _Resolved(kind="color3", socket=comb.outputs["Color"])


def build_colorcorrect_recipe(
    nodes: Any, links: Any, in_resolved: _Resolved, hue: _Resolved,
    saturation: _Resolved, gamma: _Resolved, lift: _Resolved, gain: _Resolved,
    contrast: _Resolved, contrastpivot: _Resolved, exposure: _Resolved,
    cursor: dict[str, float], depth: int,
) -> _Resolved:
    """Assemble the colorcorrect expression from Blender shader nodes.

    Follows ``NG_colorcorrect_color3`` from the MaterialX standard library:
        hue rotation -> saturate (luminance mix) -> pow(1/gamma) ->
        * (1 - lift) + lift -> * gain -> (- pivot) * contrast + pivot ->
        * 2^exposure

    All arguments are already-resolved terms (Group Input sockets when
    called from inside the node group).
    """
    d = depth + 1

    # 1) Hue rotation: split RGB -> HSV, H += hue (wrapped to 0-1), recombine.
    #    (colorcorrect calls hsvadjust with S/V multipliers fixed to 1, so
    #    only the hue rotation is needed.)
    sep = _place(nodes.new("ShaderNodeSeparateColor"), cursor, d)
    sep.mode = "HSV"
    _assign(links, sep.inputs[0], in_resolved)
    hue_shifted = _mathop(
        nodes, links, "ADD",
        _Resolved(kind="float", socket=sep.outputs[0]), hue, cursor, d,
    )
    hue_wrapped = _place(nodes.new("ShaderNodeMath"), cursor, d)
    hue_wrapped.operation = "WRAP"
    links.new(hue_shifted.socket, hue_wrapped.inputs[0])
    hue_wrapped.inputs[1].default_value = 0.0
    hue_wrapped.inputs[2].default_value = 1.0
    comb = _place(nodes.new("ShaderNodeCombineColor"), cursor, d)
    comb.mode = "HSV"
    links.new(hue_wrapped.outputs["Value"], comb.inputs[0])
    links.new(sep.outputs[1], comb.inputs[1])
    links.new(sep.outputs[2], comb.inputs[2])
    hue_adjusted = _Resolved(kind="color3", socket=comb.outputs["Color"])

    # 2) Saturate: gray = luminance(in, lumacoeffs);
    #    mix(fg=in, bg=gray, t=saturation)
    luma_const = _Resolved(kind="vector3", value=list(_LUMA_COEFFS_ACESCG))
    gray_scalar = _vecmath(
        nodes, links, "DOT_PRODUCT", hue_adjusted, luma_const, cursor, d, kind="float",
    )
    gray = _broadcast_to_color(nodes, links, gray_scalar, cursor, d)
    mix_node = _place(nodes.new("ShaderNodeMix"), cursor, d)
    mix_node.data_type = "RGBA"
    # MaterialX allows over-saturation (saturation > 1); the Mix node clamps
    # its factor to 0-1 by default, which would silently cap it.
    mix_node.clamp_factor = False
    _assign(links, mix_node.inputs["Factor"], saturation)
    _assign(links, mix_node.inputs["A"], gray)          # bg
    _assign(links, mix_node.inputs["B"], hue_adjusted)  # fg
    saturated = _Resolved(kind="color3", socket=mix_node.outputs["Result"])

    # 3) Gamma: pow(saturated, 1/gamma). The inlow/inhigh/outlow/outhigh
    #    parameters of the underlying range node are identity, so the range
    #    reduces to a plain power.
    inv_gamma = _mathop(
        nodes, links, "DIVIDE", _Resolved(kind="float", value=1.0), gamma, cursor, d,
    )
    after_gamma = _vec_power(nodes, links, saturated, inv_gamma, cursor, d)

    # 4) Lift: after_gamma * (1 - lift) + lift
    one_minus_lift = _mathop(
        nodes, links, "SUBTRACT", _Resolved(kind="float", value=1.0), lift, cursor, d,
    )
    after_lift = _vecmath(
        nodes, links, "ADD",
        _vecmath(
            nodes, links, "MULTIPLY", after_gamma,
            _broadcast_to_color(nodes, links, one_minus_lift, cursor, d), cursor, d,
        ),
        _broadcast_to_color(nodes, links, lift, cursor, d), cursor, d,
    )

    # 5) Gain: after_lift * gain
    after_gain = _vecmath(
        nodes, links, "MULTIPLY", after_lift,
        _broadcast_to_color(nodes, links, gain, cursor, d), cursor, d,
    )

    # 6) Contrast: (after_gain - pivot) * contrast + pivot
    pivot_color = _broadcast_to_color(nodes, links, contrastpivot, cursor, d)
    after_contrast = _vecmath(
        nodes, links, "ADD",
        _vecmath(
            nodes, links, "MULTIPLY",
            _vecmath(nodes, links, "SUBTRACT", after_gain, pivot_color, cursor, d),
            _broadcast_to_color(nodes, links, contrast, cursor, d), cursor, d,
        ),
        pivot_color, cursor, d,
    )

    # 7) Exposure: after_contrast * 2^exposure
    exposure_pow = _mathop(
        nodes, links, "POWER", _Resolved(kind="float", value=2.0), exposure, cursor, d,
    )
    return _vecmath(
        nodes, links, "MULTIPLY", after_contrast,
        _broadcast_to_color(nodes, links, exposure_pow, cursor, d), cursor, depth,
    )


def get_colorcorrect_group() -> "bpy.types.NodeTree":
    """Return the shared colorcorrect Node Group, building it if missing.

    A single shared definition keeps materials light: without it, every use
    would expand ~30 nodes into the material's node tree.

    The group is identified by the GROUP_MARKER custom property, not by its
    name, so node groups created by other tools under the same name are left
    alone (Blender will suffix ours with ".001" in that case, which is fine).

    An existing group is returned untouched. Rebuilding the interface/nodes
    of a group that other materials already reference would regenerate the
    input sockets of their ShaderNodeGroup instances and silently disconnect
    all of their external links (observed in practice with two or more
    materials sharing the group). To pick up changes to the recipe after an
    update, delete the "Color Correct (MaterialX)" node group manually and
    re-add the node.

    Returns:
        The shared NodeTree (for use in a ShaderNodeGroup).
    """
    for existing in bpy.data.node_groups:
        if existing.get(GROUP_MARKER):
            return existing

    group = bpy.data.node_groups.new(GROUP_NAME, "ShaderNodeTree")
    group[GROUP_MARKER] = True
    for _key, label, socket_type in INPUT_SOCKETS:
        group.interface.new_socket(name=label, in_out="INPUT", socket_type=socket_type)
    group.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")

    cursor = {"y": 400.0}
    group_input = group.nodes.new("NodeGroupInput")
    group_input.location = (-1600, 0)
    group_output = group.nodes.new("NodeGroupOutput")

    def _from_input(label: str, kind: str) -> _Resolved:
        return _Resolved(kind=kind, socket=group_input.outputs[label])

    result = build_colorcorrect_recipe(
        group.nodes, group.links,
        _from_input("In", "color3"),
        _from_input("Hue", "float"),
        _from_input("Saturation", "float"),
        _from_input("Gamma", "float"),
        _from_input("Lift", "float"),
        _from_input("Gain", "float"),
        _from_input("Contrast", "float"),
        _from_input("Contrast Pivot", "float"),
        _from_input("Exposure", "float"),
        cursor, 0,
    )
    group.links.new(result.socket, group_output.inputs["Color"])
    group_output.location = (200, 0)
    return group


class NODE_OT_add_materialx_colorcorrect(bpy.types.Operator):
    """Add the Color Correct (MaterialX) node group to the current shader tree."""

    bl_idname = "node.add_materialx_colorcorrect"
    bl_label = "Color Correct (MaterialX)"
    bl_description = (
        "Add a node group that recreates the MaterialX colorcorrect node "
        "(In / Hue / Saturation / Gamma / Lift / Gain / Contrast / "
        "Contrast Pivot / Exposure)"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: "bpy.types.Context") -> bool:
        space = context.space_data
        return (
            space is not None
            and space.type == "NODE_EDITOR"
            and space.tree_type == "ShaderNodeTree"
            and space.edit_tree is not None
        )

    def execute(self, context: "bpy.types.Context") -> set[str]:
        tree = context.space_data.edit_tree
        group = get_colorcorrect_group()
        for node in tree.nodes:
            node.select = False
        node = tree.nodes.new("ShaderNodeGroup")
        node.node_tree = group
        node.location = context.space_data.cursor_location
        node.select = True
        tree.nodes.active = node
        return {"FINISHED"}

    def invoke(
        self, context: "bpy.types.Context", event: "bpy.types.Event"
    ) -> set[str]:
        result = self.execute(context)
        if result == {"FINISHED"}:
            # Attach the new node to the mouse, matching the behaviour of
            # the built-in Add menu entries.
            bpy.ops.node.translate_attach_remove_on_cancel("INVOKE_DEFAULT")
        return result


def _menu_draw(self: "bpy.types.Menu", context: "bpy.types.Context") -> None:
    # Once the group exists in the file, Blender's built-in group listing in
    # this same menu already offers it by name; showing our operator entry as
    # well would look like a duplicate, so skip it.
    for group in bpy.data.node_groups:
        if group.get(GROUP_MARKER):
            return
    self.layout.operator(
        NODE_OT_add_materialx_colorcorrect.bl_idname,
        text="Color Correct (MaterialX)",
    )


_CLASSES = (NODE_OT_add_materialx_colorcorrect,)

# The Add > Group submenu was renamed across Blender versions:
#   - Blender 5.x: NODE_MT_group_add (shared by all node editors)
#   - Blender 4.x: NODE_MT_category_shader_group (shader editor specific)
_GROUP_MENU_CANDIDATES = ("NODE_MT_group_add", "NODE_MT_category_shader_group")


def _group_menu() -> "type[bpy.types.Menu] | None":
    """Return the Add > Group menu type for the running Blender version."""
    for name in _GROUP_MENU_CANDIDATES:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            return menu
    return None


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    menu = _group_menu()
    if menu is not None:
        menu.append(_menu_draw)


def unregister() -> None:
    menu = _group_menu()
    if menu is not None:
        menu.remove(_menu_draw)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
