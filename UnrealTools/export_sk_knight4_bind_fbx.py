"""
Export the exact SK_Knight4 skeletal mesh/bind pose from Unreal as FBX.

Run inside Unreal Editor Python:

    exec(open(r"C:/OCTOPI_Pipeline/UnrealTools/export_sk_knight4_bind_fbx.py").read())

The exported FBX is used by MoveAIStyleTests/make_knight4_animation_fbx.py so
Blender can animate the real Knight4 skeleton instead of inventing a compatible
one from scratch.
"""

from __future__ import annotations

import unreal


SKELETAL_MESH = "/Game/Characters/Knight4/SK_Knight4"
EXPORT_PATH = "C:/OCTOPI_Pipeline/outputs/gold_mocap_full_217f_mesh_dummy_fbx/SK_Knight4_bindpose.fbx"


def log(message: str) -> None:
    unreal.log(f"[OctopiKnightExport] {message}")


def main() -> None:
    mesh = unreal.load_asset(SKELETAL_MESH)
    if not mesh:
        raise RuntimeError(f"Could not load skeletal mesh: {SKELETAL_MESH}")

    task = unreal.AssetExportTask()
    task.object = mesh
    task.filename = EXPORT_PATH
    task.automated = True
    task.prompt = False
    task.replace_identical = True

    options = unreal.FbxExportOption()
    # Keep the reference mesh/skeleton payload. We do not need animation in this
    # bind-pose export; it is only used as the skeleton authority.
    for prop, value in (
        ("ascii", False),
        ("collision", False),
        ("level_of_detail", False),
        ("vertex_color", True),
        ("export_morph_targets", False),
        ("export_preview_mesh", True),
        ("map_skeletal_motion_to_root", False),
    ):
        try:
            options.set_editor_property(prop, value)
        except Exception:
            pass
    task.options = options

    ok = unreal.Exporter.run_asset_export_task(task)
    if not ok:
        raise RuntimeError(f"FBX export failed: {EXPORT_PATH}")

    log(f"Exported {SKELETAL_MESH}")
    log(f"FBX: {EXPORT_PATH}")


if __name__ == "__main__":
    main()
