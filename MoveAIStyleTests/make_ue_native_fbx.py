import argparse
import subprocess
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Create UE-native mannequin-style FBX from skeleton_animation.json")
    parser.add_argument("--folder", default="outputs/gold_mocap_full_217f_mesh_dummy_fbx")
    parser.add_argument("--blender", default=r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
    return parser.parse_args()


def write_blender_script(folder):
    folder = Path(folder).resolve()
    script_path = folder / "make_ue_native_fbx_blender.py"
    script = r'''
import json
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

BASE = Path(r"__BASE__")
DATA = json.loads((BASE / "skeleton_animation.json").read_text(encoding="utf-8"))
FRAMES = DATA["frames"]
FPS = float(DATA.get("fps", 60))

UE_BONES = [
    ("root", None),
    ("pelvis", "root"),
    ("spine_01", "pelvis"),
    ("spine_02", "spine_01"),
    ("spine_03", "spine_02"),
    ("neck_01", "spine_03"),
    ("head", "neck_01"),
    ("upperarm_l", "spine_03"),
    ("lowerarm_l", "upperarm_l"),
    ("hand_l", "lowerarm_l"),
    ("upperarm_r", "spine_03"),
    ("lowerarm_r", "upperarm_r"),
    ("hand_r", "lowerarm_r"),
    ("thigh_l", "pelvis"),
    ("calf_l", "thigh_l"),
    ("foot_l", "calf_l"),
    ("thigh_r", "pelvis"),
    ("calf_r", "thigh_r"),
    ("foot_r", "calf_r"),
]

def frame_points(frame):
    pts = {}
    for key, value in frame.items():
        if key == "frame":
            continue
        pts[key] = Vector((float(value[0]), float(value[1]), float(value[2])))
    if "nose" in pts and "neck" in pts:
        head_dir = pts["nose"] - pts["neck"]
        if head_dir.length < 1e-6:
            head_dir = Vector((0, 0, 1))
        pts["head_tip"] = pts["nose"] + head_dir.normalized() * 0.45
    return pts

raw_rest = frame_points(FRAMES[0])
base_pelvis = raw_rest.get("pelvis", Vector((0, 0, 0))).copy()
ground_z = min(
    [raw_rest[name].z for name in ("left_ankle", "right_ankle") if name in raw_rest],
    default=0.0,
)

def normalized_points(frame):
    raw = frame_points(frame)
    pelvis = raw.get("pelvis", base_pelvis)
    origin = Vector((pelvis.x, pelvis.y, ground_z))
    pts = {name: value - origin for name, value in raw.items()}
    pts["__root__"] = Vector((0, 0, 0))
    return pts

def midpoint(pts, a, b, fallback):
    if a in pts and b in pts:
        return (pts[a] + pts[b]) * 0.5
    return pts.get(a, pts.get(b, fallback)).copy()

def lerp(a, b, t):
    return a + (b - a) * t

def safe_dir(a, b, fallback=Vector((0, 0, 1))):
    vec = b - a
    if vec.length < 1e-6:
        return fallback.normalized()
    return vec.normalized()

def ue_joint_positions(pts):
    pelvis = pts.get("pelvis", Vector((0, 0, 0)))
    neck = pts.get("neck", pelvis + Vector((0, 0, 0.6)))
    nose = pts.get("nose", neck + Vector((0, 0, 0.3)))
    head_tip = pts.get("head_tip", nose + Vector((0, 0, 0.25)))

    left_shoulder = pts.get("left_shoulder", neck + Vector((0.25, 0, 0)))
    right_shoulder = pts.get("right_shoulder", neck + Vector((-0.25, 0, 0)))
    left_elbow = pts.get("left_elbow", left_shoulder + Vector((0.35, 0, -0.25)))
    right_elbow = pts.get("right_elbow", right_shoulder + Vector((-0.35, 0, -0.25)))
    left_wrist = pts.get("left_wrist", left_elbow + Vector((0.35, 0, -0.15)))
    right_wrist = pts.get("right_wrist", right_elbow + Vector((-0.35, 0, -0.15)))

    left_hip = pts.get("left_hip", pelvis + Vector((0.15, 0, -0.05)))
    right_hip = pts.get("right_hip", pelvis + Vector((-0.15, 0, -0.05)))
    left_knee = pts.get("left_knee", left_hip + Vector((0, 0, -0.45)))
    right_knee = pts.get("right_knee", right_hip + Vector((0, 0, -0.45)))
    left_ankle = pts.get("left_ankle", left_knee + Vector((0, 0, -0.45)))
    right_ankle = pts.get("right_ankle", right_knee + Vector((0, 0, -0.45)))

    torso_tip = neck
    hand_l_tip = left_wrist + safe_dir(left_elbow, left_wrist, Vector((1, 0, 0))) * 0.22
    hand_r_tip = right_wrist + safe_dir(right_elbow, right_wrist, Vector((-1, 0, 0))) * 0.22
    foot_l_tip = left_ankle + Vector((0, 0.28, 0.0))
    foot_r_tip = right_ankle + Vector((0, 0.28, 0.0))

    return {
        "root": pts["__root__"],
        "pelvis": pelvis,
        "spine_01": lerp(pelvis, torso_tip, 0.33),
        "spine_02": lerp(pelvis, torso_tip, 0.60),
        "spine_03": torso_tip,
        "neck_01": neck,
        "head": nose,
        "head_tip": head_tip,
        "upperarm_l": left_shoulder,
        "lowerarm_l": left_elbow,
        "hand_l": left_wrist,
        "hand_l_tip": hand_l_tip,
        "upperarm_r": right_shoulder,
        "lowerarm_r": right_elbow,
        "hand_r": right_wrist,
        "hand_r_tip": hand_r_tip,
        "thigh_l": left_hip,
        "calf_l": left_knee,
        "foot_l": left_ankle,
        "foot_l_tip": foot_l_tip,
        "thigh_r": right_hip,
        "calf_r": right_knee,
        "foot_r": right_ankle,
        "foot_r_tip": foot_r_tip,
    }

TAIL_TARGETS = {
    "root": "pelvis",
    "pelvis": "spine_01",
    "spine_01": "spine_02",
    "spine_02": "spine_03",
    "spine_03": "neck_01",
    "neck_01": "head",
    "head": "head_tip",
    "upperarm_l": "lowerarm_l",
    "lowerarm_l": "hand_l",
    "hand_l": "hand_l_tip",
    "upperarm_r": "lowerarm_r",
    "lowerarm_r": "hand_r",
    "hand_r": "hand_r_tip",
    "thigh_l": "calf_l",
    "calf_l": "foot_l",
    "foot_l": "foot_l_tip",
    "thigh_r": "calf_r",
    "calf_r": "foot_r",
    "foot_r": "foot_r_tip",
}

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

def bone_segment(pos, bone):
    head = pos[bone]
    tail = pos[TAIL_TARGETS[bone]]
    if (tail - head).length < 1e-6:
        tail = head + Vector((0, 0, 0.1))
    return head, tail

def add_capsule_section(verts, faces, weights, bone, head, tail, radius):
    direction = tail - head
    if direction.length < 1e-6:
        direction = Vector((0, 0, 1))
    y_axis = direction.normalized()
    up = Vector((0, 0, 1))
    if abs(y_axis.dot(up)) > 0.95:
        up = Vector((1, 0, 0))
    x_axis = up.cross(y_axis).normalized()
    z_axis = x_axis.cross(y_axis).normalized()
    start = len(verts)
    sides = 8
    import math
    for center in (head, tail):
        for idx in range(sides):
            angle = 2.0 * math.pi * idx / sides
            pos = center + radius * (math.cos(angle) * x_axis + math.sin(angle) * z_axis)
            verts.append((pos.x, pos.y, pos.z))
            weights.append(bone)
    for idx in range(sides):
        faces.append((start + idx, start + ((idx + 1) % sides), start + sides + ((idx + 1) % sides), start + sides + idx))
    faces.append(tuple(start + idx for idx in range(sides - 1, -1, -1)))
    faces.append(tuple(start + sides + idx for idx in range(sides)))

def create_skinned_mesh(arm, rest_pos):
    verts, faces, weights = [], [], []
    radii = {
        "pelvis": 0.18, "spine_01": 0.16, "spine_02": 0.15, "spine_03": 0.14,
        "neck_01": 0.08, "head": 0.13,
        "upperarm_l": 0.08, "lowerarm_l": 0.07, "hand_l": 0.06,
        "upperarm_r": 0.08, "lowerarm_r": 0.07, "hand_r": 0.06,
        "thigh_l": 0.105, "calf_l": 0.085, "foot_l": 0.07,
        "thigh_r": 0.105, "calf_r": 0.085, "foot_r": 0.07,
    }
    for bone, _parent in UE_BONES:
        if bone == "root":
            continue
        head, tail = bone_segment(rest_pos, bone)
        add_capsule_section(verts, faces, weights, bone, head, tail, radii.get(bone, 0.075))
    mesh = bpy.data.meshes.new("OctopiDummy_UE_native_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("OctopiDummy_UE_native", mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = arm
    groups = {bone: obj.vertex_groups.new(name=bone) for bone, _parent in UE_BONES}
    for idx, bone in enumerate(weights):
        groups[bone].add([idx], 1.0, "ADD")
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    return obj

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()
bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = len(FRAMES)
bpy.context.scene.render.fps = int(round(FPS))

rest_pts = normalized_points(FRAMES[0])
rest_pos = ue_joint_positions(rest_pts)

bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
arm = bpy.context.object
arm.name = "Armature"
arm.data.name = "OctopiDummy_UE_native_Skeleton"
arm.show_in_front = True
arm.location = (0, 0, 0)
arm.rotation_euler = (0, 0, 0)
arm.scale = (1, 1, 1)

edit_bones = arm.data.edit_bones
default = edit_bones[0]
default.name = "root"
created = {"root": default}
for bone, parent in UE_BONES:
    eb = default if bone == "root" else edit_bones.new(bone)
    head, tail = bone_segment(rest_pos, bone)
    eb.head = head
    eb.tail = tail
    eb.roll = 0
    if parent:
        eb.parent = created[parent]
        eb.use_connect = False
    created[bone] = eb

bpy.ops.object.mode_set(mode="POSE")
for pb in arm.pose.bones:
    pb.rotation_mode = "QUATERNION"

mesh_obj = create_skinned_mesh(arm, rest_pos)

for frame_idx, frame in enumerate(FRAMES, start=1):
    bpy.context.scene.frame_set(frame_idx)
    pts = normalized_points(frame)
    pos = ue_joint_positions(pts)
    for bone, _parent in UE_BONES:
        pb = arm.pose.bones[bone]
        head, tail = bone_segment(pos, bone)
        pb.matrix = matrix_from_segment(head, tail)
        pb.keyframe_insert(data_path="location", frame=frame_idx)
        pb.keyframe_insert(data_path="rotation_quaternion", frame=frame_idx)
        pb.keyframe_insert(data_path="scale", frame=frame_idx)

bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
mesh_obj.select_set(True)
bpy.context.view_layer.objects.active = arm

for action in bpy.data.actions:
    action.name = "RTMPose_Test_Anim"

blend_path = BASE / "OctopiDummy_UE_native.blend"
fbx_path = BASE / "OctopiDummy_UE_native.fbx"
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
print(f"Saved {blend_path}")
print(f"Saved {fbx_path}")
'''
    script_path.write_text(script.replace("__BASE__", str(folder)).strip() + "\n", encoding="utf-8")
    return script_path


def main():
    args = parse_args()
    folder = Path(args.folder).resolve()
    if not (folder / "skeleton_animation.json").exists():
        raise FileNotFoundError(folder / "skeleton_animation.json")
    script = write_blender_script(folder)
    subprocess.run([args.blender, "--background", "--python", str(script)], check=True)
    print(f"UE-native FBX written to: {folder / 'OctopiDummy_UE_native.fbx'}")


if __name__ == "__main__":
    main()
