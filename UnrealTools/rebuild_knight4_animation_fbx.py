"""
One-command rebuild of the proper SK_Knight4 animation FBX.

Run inside Unreal Editor Python:

    exec(open(r"C:/OCTOPI_Pipeline/UnrealTools/rebuild_knight4_animation_fbx.py").read())

This script:
1. Exports the exact SK_Knight4 bind-pose FBX from Unreal.
2. Runs Blender/Python to bake RTMPose motion onto that exact skeleton.
3. Writes OctopiDummy_SK_Knight4_anim.fbx.

It does not use the invented RTMPose/COCO skeleton and does not require Unreal
retargeting.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import unreal


ROOT = Path("C:/OCTOPI_Pipeline")
OUT = ROOT / "outputs/gold_mocap_full_217f_mesh_dummy_fbx"
SKELETAL_MESH = "/Game/Characters/Knight4/SK_Knight4"
SKELETAL_MESH_NAME_HINTS = ("SK_Knight4", "Knight4", "Knight")
BIND_FBX = OUT / "SK_Knight4_bindpose.fbx"
FINAL_FBX = OUT / "OctopiDummy_SK_Knight4_anim.fbx"
PYTHON = ROOT / "venvs/rtmpose/Scripts/python.exe"
BAKER = ROOT / "MoveAIStyleTests/make_knight4_animation_fbx.py"
BLENDER = Path("C:/Program Files/Blender Foundation/Blender 5.1/blender.exe")


def log(message: str) -> None:
    unreal.log(f"[OctopiRebuildKnight4] {message}")


def is_skeletal_mesh(asset) -> bool:
    skeletal_mesh_class = getattr(unreal, "SkeletalMesh", None)
    if skeletal_mesh_class is not None and isinstance(asset, skeletal_mesh_class):
        return True
    return asset is not None and asset.get_class().get_name() == "SkeletalMesh"


def find_knight_skeletal_mesh():
    mesh = unreal.load_asset(SKELETAL_MESH)
    if mesh and is_skeletal_mesh(mesh):
        log(f"Loaded configured skeletal mesh: {SKELETAL_MESH}")
        return mesh

    log(f"Configured skeletal mesh path was not found: {SKELETAL_MESH}")
    log("Searching /Game for a Knight skeletal mesh...")

    candidates = []
    asset_paths = unreal.EditorAssetLibrary.list_assets("/Game", recursive=True, include_folder=False)
    for path in asset_paths:
        name = path.rsplit("/", 1)[-1]
        if "." in name:
            name = name.rsplit(".", 1)[-1]
        if not any(hint.lower() in name.lower() or hint.lower() in path.lower() for hint in SKELETAL_MESH_NAME_HINTS):
            continue
        asset = unreal.load_asset(path)
        if asset and is_skeletal_mesh(asset):
            score = 0
            lowered = path.lower()
            if "sk_knight4" in lowered:
                score += 100
            if "knight4" in lowered:
                score += 50
            if "sk_" in name.lower():
                score += 10
            candidates.append((score, path, asset))

    if not candidates:
        raise RuntimeError(
            "Could not find any SkeletalMesh matching Knight4/Knight under /Game. "
            "Open the knight skeletal mesh in Unreal and copy its Reference Viewer path into SKELETAL_MESH."
        )

    candidates.sort(key=lambda item: (-item[0], item[1]))
    log("Skeletal mesh candidates:")
    for score, path, _asset in candidates[:20]:
        log(f"  score={score:03d} {path}")

    chosen_score, chosen_path, chosen_asset = candidates[0]
    log(f"Auto-selected skeletal mesh: {chosen_path}")
    return chosen_asset


def export_bind_pose() -> None:
    mesh = find_knight_skeletal_mesh()

    OUT.mkdir(parents=True, exist_ok=True)

    task = unreal.AssetExportTask()
    task.object = mesh
    task.filename = str(BIND_FBX).replace("\\", "/")
    task.automated = True
    task.prompt = False
    task.replace_identical = True

    options = unreal.FbxExportOption()
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
    if not ok or not BIND_FBX.exists():
        raise RuntimeError(f"Failed to export Knight4 bind pose to: {BIND_FBX}")

    log(f"Exported bind pose: {BIND_FBX}")


def run_baker() -> None:
    if not PYTHON.exists():
        raise RuntimeError(f"Missing RTMPose Python: {PYTHON}")
    if not BAKER.exists():
        raise RuntimeError(f"Missing baker script: {BAKER}")
    if not BLENDER.exists():
        raise RuntimeError(f"Missing Blender executable: {BLENDER}")

    cmd = [
        str(PYTHON),
        str(BAKER),
        "--folder",
        str(OUT),
        "--knight-fbx",
        str(BIND_FBX),
        "--blender",
        str(BLENDER),
    ]
    log("Running baker:")
    log(" ".join(cmd))
    subprocess.run(cmd, check=True)

    if not FINAL_FBX.exists():
        raise RuntimeError(f"Baker finished but final FBX is missing: {FINAL_FBX}")
    log(f"Rebuilt final FBX: {FINAL_FBX}")


def main() -> None:
    log("Starting proper Knight4 FBX rebuild")
    export_bind_pose()
    run_baker()
    log("Done")


if __name__ == "__main__":
    main()
