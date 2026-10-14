import argparse
import subprocess
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Export raw animated RTMPose joint markers with no armature solving")
    parser.add_argument("--folder", default="outputs/gold_mocap_full_217f_mesh_dummy_fbx")
    parser.add_argument("--blender", default=r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
    parser.add_argument("--render-preview", default="true")
    return parser.parse_args()


def write_blender_script(folder: Path, render_preview: bool) -> Path:
    script_path = folder / "export_raw_joint_markers_blender.py"
    script = r'''
import json
from pathlib import Path

import bpy
from mathutils import Vector

BASE = Path(r"__BASE__")
RENDER_PREVIEW = __RENDER_PREVIEW__
DATA = json.loads((BASE / "skeleton_animation.json").read_text(encoding="utf-8"))
FRAMES = DATA["frames"]
FPS = int(round(float(DATA.get("fps", 60))))

JOINTS = [
    "pelvis",
    "neck",
    "nose",
    "left_shoulder",
    "left_elbow",
    "left_wrist",
    "right_shoulder",
    "right_elbow",
    "right_wrist",
    "left_hip",
    "left_knee",
    "left_ankle",
    "right_hip",
    "right_knee",
    "right_ankle",
]

EDGES = [
    ("pelvis", "neck"),
    ("neck", "nose"),
    ("neck", "left_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("neck", "right_shoulder"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
    ("pelvis", "left_hip"),
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("pelvis", "right_hip"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
]


def point(frame, name):
    value = frame.get(name)
    if value is None:
        return None
    return Vector((float(value[0]), float(value[1]), float(value[2])))


raw_rest = {name: point(FRAMES[0], name) for name in JOINTS}
base_pelvis = raw_rest.get("pelvis") or Vector((0, 0, 0))
ground_z = min(
    [p.z for name, p in raw_rest.items() if name in ("left_ankle", "right_ankle") and p is not None],
    default=0.0,
)


def normalized_point(frame, name):
    p = point(frame, name)
    pelvis = point(frame, "pelvis") or base_pelvis
    if p is None:
        return None
    origin = Vector((pelvis.x, pelvis.y, ground_z))
    return p - origin


def make_material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()

bpy.context.scene.frame_start = 0
bpy.context.scene.frame_end = len(FRAMES) - 1
bpy.context.scene.render.fps = FPS

mat_joint = make_material("Octopi_Joints_Yellow", (1.0, 0.72, 0.02, 1.0))
mat_edge = make_material("Octopi_Edges_Green", (0.0, 0.75, 0.12, 1.0))

joint_objects = {}
for name in JOINTS:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.045, location=(0, 0, 0))
    obj = bpy.context.object
    obj.name = f"joint_{name}"
    obj.data.name = f"mesh_joint_{name}"
    obj.data.materials.append(mat_joint)
    joint_objects[name] = obj

edge_objects = {}
for a, b in EDGES:
    curve = bpy.data.curves.new(f"edge_{a}_to_{b}", "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_depth = 0.015
    spl = curve.splines.new("POLY")
    spl.points.add(1)
    obj = bpy.data.objects.new(curve.name, curve)
    obj.data.materials.append(mat_edge)
    bpy.context.collection.objects.link(obj)
    edge_objects[(a, b)] = obj

for frame_idx, frame in enumerate(FRAMES):
    bpy.context.scene.frame_set(frame_idx)

    positions = {}
    for name, obj in joint_objects.items():
        p = normalized_point(frame, name)
        if p is None:
            obj.hide_viewport = True
            obj.hide_render = True
        else:
            obj.hide_viewport = False
            obj.hide_render = False
            obj.location = p
            positions[name] = p
        obj.keyframe_insert(data_path="location", frame=frame_idx)
        obj.keyframe_insert(data_path="hide_viewport", frame=frame_idx)
        obj.keyframe_insert(data_path="hide_render", frame=frame_idx)

    for (a, b), obj in edge_objects.items():
        spl = obj.data.splines[0]
        pa = positions.get(a)
        pb = positions.get(b)
        visible = pa is not None and pb is not None
        if not visible:
            pa = pb = Vector((0, 0, 0))
        spl.points[0].co = (pa.x, pa.y, pa.z, 1)
        spl.points[1].co = (pb.x, pb.y, pb.z, 1)
        obj.hide_viewport = not visible
        obj.hide_render = not visible
        # Curve point coordinates do not keyframe nicely as nested arrays in
        # all Blender versions, so animate with a driver-safe geometry refresh:
        spl.points[0].keyframe_insert(data_path="co", frame=frame_idx)
        spl.points[1].keyframe_insert(data_path="co", frame=frame_idx)
        obj.keyframe_insert(data_path="hide_viewport", frame=frame_idx)
        obj.keyframe_insert(data_path="hide_render", frame=frame_idx)

# A simple camera and light for quick visual checks.
bpy.ops.object.light_add(type="AREA", location=(0, -4, 4))
bpy.context.object.name = "preview_area_light"
bpy.context.object.data.energy = 450
bpy.context.object.data.size = 5

bpy.ops.object.camera_add(location=(0, -4.5, 1.35), rotation=(1.35, 0, 0))
bpy.context.scene.camera = bpy.context.object

blend_path = BASE / "Octopi_raw_joint_markers.blend"
fbx_path = BASE / "Octopi_raw_joint_markers.fbx"
bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.fbx(
    filepath=str(fbx_path),
    use_selection=True,
    object_types={"MESH", "OTHER", "EMPTY", "CAMERA", "LIGHT"},
    bake_anim=True,
    bake_anim_use_all_bones=False,
    bake_anim_use_nla_strips=False,
    bake_anim_use_all_actions=False,
    apply_unit_scale=True,
    apply_scale_options="FBX_SCALE_ALL",
)

if RENDER_PREVIEW:
    preview_dir = BASE / "Octopi_raw_joint_markers_preview_frames"
    preview_dir.mkdir(exist_ok=True)
    bpy.context.scene.render.resolution_x = 1280
    bpy.context.scene.render.resolution_y = 720
    bpy.context.scene.render.image_settings.file_format = "PNG"
    bpy.context.scene.render.filepath = str(preview_dir / "frame_")
    try:
        bpy.ops.render.opengl(animation=True, view_context=False)
        print(f"Saved preview PNG frames to {preview_dir}")
    except Exception as exc:
        print(f"Preview render failed: {exc}")

print(f"Saved {blend_path}")
print(f"Saved {fbx_path}")
'''
    script_path.write_text(
        script.replace("__BASE__", str(folder)).replace("__RENDER_PREVIEW__", "True" if render_preview else "False").strip() + "\n",
        encoding="utf-8",
    )
    return script_path


def main():
    args = parse_args()
    folder = Path(args.folder).resolve()
    if not (folder / "skeleton_animation.json").exists():
        raise FileNotFoundError(folder / "skeleton_animation.json")
    script = write_blender_script(folder, args.render_preview.lower() == "true")
    subprocess.run([args.blender, "--background", "--python", str(script)], check=True)
    print(f"Raw marker blend written to: {folder / 'Octopi_raw_joint_markers.blend'}")
    print(f"Raw marker FBX written to: {folder / 'Octopi_raw_joint_markers.fbx'}")
    if args.render_preview.lower() == "true":
        print(f"Preview PNG frames written to: {folder / 'Octopi_raw_joint_markers_preview_frames'}")


if __name__ == "__main__":
    main()
