# extensions.blender.org 提出用の説明文ドラフト
#
# アップロードフォームの Description 欄にコピペしてください（Markdown対応）。
# ---

Recreates the MaterialX `colorcorrect` compound node as a shader Node Group,
built entirely from Blender's built-in shader nodes (Math, Vector Math, Mix,
Separate/Combine Color).

Useful when authoring materials in Blender that need to match a look developed
in MaterialX-based pipelines (Houdini/Solaris, Karma, USD workflows), where
`colorcorrect` is a common grading node that has no direct Blender equivalent.

## What it does

Adds one menu entry to the Shader Editor:

**Add > Group > Color Correct (MaterialX)**

This inserts a Node Group with the same inputs as the MaterialX node, applied
in the same order as the MaterialX definition (`NG_colorcorrect_color3` from
the MaterialX standard library):

- **In** — input color (scene-linear)
- **Hue** — hue rotation (0-1 wraps around the hue wheel)
- **Saturation** — saturation multiplier (values above 1 over-saturate,
  matching MaterialX behavior)
- **Gamma** — gamma correction
- **Lift** — lifts shadows toward the lift value
- **Gain** — multiplies the result
- **Contrast** / **Contrast Pivot** — contrast around a pivot value
- **Exposure** — multiplies by 2^exposure

A single shared Node Group is created on first use and reused afterwards, so
adding the node to many materials stays lightweight. Works with both Cycles
and EEVEE (plain shader nodes only, no custom rendering code, no external
dependencies).

The output has been numerically verified against the published MaterialX
formula. The luminance coefficients used by the saturation stage are the
MaterialX defaults (ACEScg primaries).

## Notes

This is an independent, unofficial recreation of the node's published formula.
It contains no code from the MaterialX project and is not affiliated with or
endorsed by the MaterialX project or the Academy Software Foundation.

Source code and issue tracker: https://github.com/sugiggy/color-correct-materialx
