import argparse
import subprocess
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Create a dead-simple RTMPose armature FBX for Blender roundtrip validation")
    parser.add_argument("--folder", default="outputs/gold_mocap_full_217f_mesh_dummy_fbx")
    parser.add_argument("--blender", default=r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
    parser.add_argument("--name", default="OctopiDummy")
    return parser.parse_args()


def write_blender_script(folder, name):
    folder = Path(folder).resolve()
    script_path = folder / "make_armature_fbx_blender.py"
    script = r'''
import json
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

BASE = Path(r"__BASE__")
RIG_NAME = "__RIG_NAME__"
DATA = json.loads((BASE / "skeleton_animation.json").read_text(encoding="utf-8"))
FRAMES = DATA["frames"]
FPS = float(DATA.get("fps", 60))

# Raw RTMPose/COCO edges only. No helper clavicles, no feet, no synthetic pose.
BONES = [
    ("pelvis", None, "pelvis", "neck", False),
    ("head", "pelvis", "neck", "nose", True),
    ("left_shoulder", "pelvis", "neck", "left_shoulder", True),
    ("left_upper_arm", "left_shoulder", "left_shoulder", "left_elbow", True),
    ("left_forearm", "left_upper_arm", "left_elbow", "left_wrist", True),
    ("right_shoulder", "pelvis", "neck", "right_shoulder", True),
    ("right_upper_arm", "right_shoulder", "right_shoulder", "right_elbow", True),
    ("right_forearm", "right_upper_arm", "right_elbow", "right_wrist", True),
    ("left_hip", "pelvis", "pelvis", "left_hip", False),
    ("left_thigh", "left_hip", "left_hip", "left_knee", True),
    ("left_calf", "left_thigh", "left_knee", "left_ankle", True),
    ("right_hip", "pelvis", "pelvis", "right_hip", False),
    ("right_thigh", "right_hip", "right_hip", "right_knee", True),
    ("right_calf", "right_thigh", "right_knee", "right_ankle", True),
]

RAW_LINES = [(a, b) for _bone, _parent, a, b, _connected in BONES]


def frame_points(frame):
    pts = {}
    for key, value in frame.items():
        if key == "frame":
            continue
        pts[key] = Vector((float(value[0]), float(value[1]), float(value[2])))
    return pts


raw_rest = frame_points(FRAMES[0])
base_pelvis = raw_rest.get("pelvis", Vector((0, 0, 0))).copy()
ground_z = min([raw_rest[k].z for k in ("left_ankle", "right_ankle") if k in raw_rest], default=0.0)


def normalized_points(frame, mode):
    raw = frame_points(frame)
    pelvis = raw.get("pelvis", base_pelvis)
    origin = Vector((pelvis.x, pelvis.y, ground_z))
    pts = {name: value - origin for name, value in raw.items()}
    pts["__root_motion__"] = Vector((0, 0, 0))
    if mode == "root_motion":
        pts["__root_motion__"] = Vector((pelvis.x - base_pelvis.x, pelvis.y - base_pelvis.y, 0))
    return pts


def bone_def(name):
    for bone in BONES:
        if bone[0] == name:
            return bone
    raise KeyError(name)


def segment(pts, bone):
    _bone, _parent, a, b, _connected = bone_def(bone)
    head = pts.get(a, Vector((0, 0, 0))).copy()
    tail = pts.get(b, head + Vector((0, 0, 0.1))).copy()
    if (tail - head).length < 1e-6:
        tail = head + Vector((0, 0, 0.1))
    return head, tail


def matrix_from_segment(head, tail):
    direction = tail - head
    if direction.length < 1e-6:
        direction = Vector((0, 0, 1))
    y_axis = direction.normalized()
    up = Vector((0, 0, 1))
    if abs(y_axis.dot(up)) > 0.95:
        up = Vector((1, 0, 0))
    x_axis = up.cross(y_axis).normalized()
    z_axis = x_axis.cross(y_axis).normalized()
    return Matrix((
        (x_axis.x, y_axis.x, z_axis.x, head.x),
        (x_axis.y, y_axis.y, z_axis.y, head.y),
        (x_axis.z, y_axis.z, z_axis.z, head.z),
        (0.0, 0.0, 0.0, 1.0),
    ))


def add_raw_preview(name, pts, material):
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    for idx, (a, b) in enumerate(RAW_LINES):
        if a not in pts or b not in pts:
            continue
        curve = bpy.data.curves.new(f"{name}_{idx:02d}", "CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 1
        curve.bevel_depth = 0.01
        spl = curve.splines.new("POLY")
        spl.points.add(1)
        pa = pts[a]
        pb = pts[b]
        spl.points[0].co = (pa.x, pa.y, pa.z, 1)
        spl.points[1].co = (pb.x, pb.y, pb.z, 1)
        obj = bpy.data.objects.new(curve.name, curve)
        obj.data.materials.append(material)
        collection.objects.link(obj)


def create_proxy_mesh(arm, rest_pts):
    # Tiny skinned cylinders, only so FBX importers see a skeletal mesh payload.
    verts, faces, weights = [], [], []
    import math
    for bone, _parent, _a, _b, _connected in BONES:
        head, tail = segment(rest_pts, bone)
        direction = tail - head
        y_axis = direction.normalized()
        up = Vector((0, 0, 1))
        if abs(y_axis.dot(up)) > 0.95:
            up = Vector((1, 0, 0))
        x_axis = up.cross(y_axis).normalized()
        z_axis = x_axis.cross(y_axis).normalized()
        start = len(verts)
        sides = 6
        radius = 0.025
        for center in (head, tail):
            for idx in range(sides):
                angle = 2.0 * math.pi * idx / sides
                p = center + radius * (math.cos(angle) * x_axis + math.sin(angle) * z_axis)
                verts.append((p.x, p.y, p.z))
                weights.append(bone)
        for idx in range(sides):
            faces.append((start + idx, start + ((idx + 1) % sides), start + sides + ((idx + 1) % sides), start + sides + idx))

    mesh = bpy.data.meshes.new(f"{RIG_NAME}_ProxyMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("OctopiDummy", mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = arm
    groups = {bone: obj.vertex_groups.new(name=bone) for bone, *_rest in BONES}
    for idx, bone in enumerate(weights):
        groups[bone].add([idx], 1.0, "ADD")
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    return obj


def build_export(mode, suffix):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = len(FRAMES) - 1
    bpy.context.scene.render.fps = int(round(FPS))

    rest_pts = normalized_points(FRAMES[0], mode)

    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    arm = bpy.context.object
    arm.name = f"{RIG_NAME}_{suffix}_Armature"
    arm.data.name = f"{RIG_NAME}_{suffix}_Skeleton"
    arm.show_in_front = True
    arm.location = (0, 0, 0)
    arm.rotation_euler = (0, 0, 0)
    arm.scale = (1, 1, 1)

    edit_bones = arm.data.edit_bones
    default = edit_bones[0]
    default.name = BONES[0][0]
    created = {}
    for bone, parent, _a, _b, connected in BONES:
        eb = default if bone == BONES[0][0] else edit_bones.new(bone)
        head, tail = segment(rest_pts, bone)
        eb.head = head
        eb.tail = tail
        eb.roll = 0.0
        if parent is not None:
            eb.parent = created[parent]
            # Only connect when the raw edge starts exactly at the parent tail.
            if connected and (head - eb.parent.tail).length < 1e-5:
                eb.head = eb.parent.tail
                eb.use_connect = True
            else:
                eb.use_connect = False
        created[bone] = eb

    bpy.ops.object.mode_set(mode="POSE")
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"

    proxy = create_proxy_mesh(arm, rest_pts)
    proxy.name = f"{RIG_NAME}_{suffix}"
    proxy.data.name = f"{RIG_NAME}_{suffix}_Mesh"

    # Frame 0 is rest pose. This must match the raw skeleton exactly.
    for frame_idx, frame in enumerate(FRAMES):
        bpy.context.scene.frame_set(frame_idx)
        pts = normalized_points(frame, mode)
        arm.location = pts["__root_motion__"]
        arm.keyframe_insert(data_path="location", frame=frame_idx)

        for bone, _parent, _a, _b, _connected in BONES:
            pb = arm.pose.bones[bone]
            if frame_idx == 0:
                pb.matrix_basis.identity()
            else:
                # Important: no pose-bone world translation. Rotation only.
                # This is not expected to be perfect yet; frame-0/rest is the
                # acceptance target for this pass.
                current = matrix_from_segment(*segment(pts, bone)).to_quaternion()
                rest = matrix_from_segment(*segment(rest_pts, bone)).to_quaternion()
                pb.rotation_quaternion = rest.inverted() @ current
            pb.keyframe_insert(data_path="rotation_quaternion", frame=frame_idx)

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    proxy.select_set(True)
    bpy.context.view_layer.objects.active = arm

    for action in bpy.data.actions:
        action.name = f"RTMPose_Test_Anim_{suffix}"

    blend_path = BASE / f"OctopiDummy_{suffix}.blend"
    fbx_path = BASE / f"OctopiDummy_{suffix}.fbx"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    bpy.ops.export_scene.fbx(
        filepath=str(fbx_path),
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        add_leaf_bones=False,
        bake_anim=True,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_ALL",
        primary_bone_axis="Y",
        secondary_bone_axis="X",
    )

    # Roundtrip check: raw yellow skeleton and imported FBX armature overlap at
    # frame 0. No offsets. If these do not match, the export is still wrong.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    mat_raw = bpy.data.materials.new("Raw_RTMPose_Yellow")
    mat_raw.diffuse_color = (1.0, 0.78, 0.0, 1.0)
    add_raw_preview("raw_rtmpose_frame0", rest_pts, mat_raw)
    bpy.ops.import_scene.fbx(filepath=str(fbx_path))
    bpy.context.scene.frame_set(0)
    check_path = BASE / f"OctopiDummy_{suffix}_roundtrip_check.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(check_path))
    print(f"Saved {blend_path}")
    print(f"Saved {fbx_path}")
    print(f"Saved {check_path}")


build_export("in_place", "in_place")
build_export("root_motion", "root_motion")
'''
    script_path.write_text(
        script.replace("__BASE__", str(folder)).replace("__RIG_NAME__", name).strip() + "\n",
        encoding="utf-8",
    )
    return script_path


def main():
    args = parse_args()
    folder = Path(args.folder).resolve()
    if not (folder / "skeleton_animation.json").exists():
        raise FileNotFoundError(folder / "skeleton_animation.json")
    script = write_blender_script(folder, args.name)
    subprocess.run([args.blender, "--background", "--python", str(script)], check=True)
    print(f"In-place armature FBX written to: {folder / 'OctopiDummy_in_place.fbx'}")
    print(f"Root-motion armature FBX written to: {folder / 'OctopiDummy_root_motion.fbx'}")
    print(f"Roundtrip check blend written to: {folder / 'OctopiDummy_in_place_roundtrip_check.blend'}")


if __name__ == "__main__":
    main()
