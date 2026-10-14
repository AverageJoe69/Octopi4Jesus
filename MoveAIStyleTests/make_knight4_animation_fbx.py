import argparse
import subprocess
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Bake RTMPose motion onto the exact SK_Knight4 bind skeleton")
    parser.add_argument("--folder", default="outputs/gold_mocap_full_217f_mesh_dummy_fbx")
    parser.add_argument("--knight-fbx", default="outputs/gold_mocap_full_217f_mesh_dummy_fbx/SK_Knight4_bindpose.fbx")
    parser.add_argument("--blender", default=r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
    return parser.parse_args()


def write_blender_script(folder, knight_fbx):
    folder = Path(folder).resolve()
    knight_fbx = Path(knight_fbx).resolve()
    script_path = folder / "make_knight4_animation_fbx_blender.py"
    script = r'''
import json
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

BASE = Path(r"__BASE__")
KNIGHT_FBX = Path(r"__KNIGHT_FBX__")
DATA = json.loads((BASE / "skeleton_animation.json").read_text(encoding="utf-8"))
FRAMES = DATA["frames"]
FPS = float(DATA.get("fps", 60))

SOLVED_BONES = [
    "root", "pelvis",
    "spine_01", "spine_02", "spine_03", "neck_01", "head",
    "upperarm_l", "lowerarm_l", "hand_l",
    "upperarm_r", "lowerarm_r", "hand_r",
    "thigh_l", "calf_l", "foot_l",
    "thigh_r", "calf_r", "foot_r",
]

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
ground_z = min([raw_rest[k].z for k in ("left_ankle", "right_ankle") if k in raw_rest], default=0.0)

def normalized_points(frame):
    raw = frame_points(frame)
    pelvis = raw.get("pelvis", base_pelvis)
    origin = Vector((pelvis.x, pelvis.y, ground_z))
    pts = {name: value - origin for name, value in raw.items()}
    pts["__root__"] = Vector((0, 0, 0))
    return pts

def lerp(a, b, t):
    return a + (b - a) * t

def safe_dir(a, b, fallback):
    vec = b - a
    if vec.length < 1e-6:
        return fallback.normalized()
    return vec.normalized()

def ue_motion_points(pts):
    pelvis = pts.get("pelvis", Vector((0, 0, 0)))
    neck = pts.get("neck", pelvis + Vector((0, 0, 0.6)))
    nose = pts.get("nose", neck + Vector((0, 0, 0.3)))
    head_tip = pts.get("head_tip", nose + Vector((0, 0, 0.3)))

    left_shoulder = pts.get("left_shoulder", neck + Vector((0.25, 0, 0)))
    right_shoulder = pts.get("right_shoulder", neck + Vector((-0.25, 0, 0)))
    left_elbow = pts.get("left_elbow", left_shoulder + Vector((0.35, 0, -0.2)))
    right_elbow = pts.get("right_elbow", right_shoulder + Vector((-0.35, 0, -0.2)))
    left_wrist = pts.get("left_wrist", left_elbow + Vector((0.35, 0, -0.1)))
    right_wrist = pts.get("right_wrist", right_elbow + Vector((-0.35, 0, -0.1)))

    left_hip = pts.get("left_hip", pelvis + Vector((0.15, 0, -0.05)))
    right_hip = pts.get("right_hip", pelvis + Vector((-0.15, 0, -0.05)))
    left_knee = pts.get("left_knee", left_hip + Vector((0, 0, -0.45)))
    right_knee = pts.get("right_knee", right_hip + Vector((0, 0, -0.45)))
    left_ankle = pts.get("left_ankle", left_knee + Vector((0, 0, -0.45)))
    right_ankle = pts.get("right_ankle", right_knee + Vector((0, 0, -0.45)))

    return {
        "root": pts["__root__"],
        "pelvis": pelvis,
        "spine_01": lerp(pelvis, neck, 0.33),
        "spine_02": lerp(pelvis, neck, 0.60),
        "spine_03": neck,
        "neck_01": neck,
        "head": nose,
        "head_tip": head_tip,
        "upperarm_l": left_shoulder,
        "lowerarm_l": left_elbow,
        "hand_l": left_wrist,
        "hand_l_tip": left_wrist + safe_dir(left_elbow, left_wrist, Vector((1, 0, 0))) * 0.2,
        "upperarm_r": right_shoulder,
        "lowerarm_r": right_elbow,
        "hand_r": right_wrist,
        "hand_r_tip": right_wrist + safe_dir(right_elbow, right_wrist, Vector((-1, 0, 0))) * 0.2,
        "thigh_l": left_hip,
        "calf_l": left_knee,
        "foot_l": left_ankle,
        "foot_l_tip": left_ankle + Vector((0, 0.25, 0)),
        "thigh_r": right_hip,
        "calf_r": right_knee,
        "foot_r": right_ankle,
        "foot_r_tip": right_ankle + Vector((0, 0.25, 0)),
    }

def projected_axis(axis, normal, fallback):
    axis = axis - normal * axis.dot(normal)
    if axis.length < 1e-6:
        axis = fallback - normal * fallback.dot(normal)
    if axis.length < 1e-6:
        axis = Vector((1, 0, 0)) - normal * Vector((1, 0, 0)).dot(normal)
    if axis.length < 1e-6:
        axis = Vector((0, 1, 0)) - normal * Vector((0, 1, 0)).dot(normal)
    return axis.normalized()

def basis_from_forward_up(forward, up_hint, fallback_up=Vector((0, 0, 1))):
    if forward.length < 1e-6:
        return None
    y_axis = forward.normalized()
    z_axis = projected_axis(up_hint, y_axis, fallback_up)
    x_axis = y_axis.cross(z_axis)
    if x_axis.length < 1e-6:
        z_axis = projected_axis(fallback_up, y_axis, Vector((1, 0, 0)))
        x_axis = y_axis.cross(z_axis)
    x_axis.normalize()
    z_axis = x_axis.cross(y_axis)
    z_axis.normalize()
    return Matrix((
        (x_axis.x, y_axis.x, z_axis.x),
        (x_axis.y, y_axis.y, z_axis.y),
        (x_axis.z, y_axis.z, z_axis.z),
    ))

def plane_hint(pos, a, b, c, fallback):
    if a not in pos or b not in pos or c not in pos:
        return fallback
    first = pos[b] - pos[a]
    second = pos[c] - pos[b]
    if first.length < 1e-6 or second.length < 1e-6:
        return fallback
    normal = first.cross(second)
    if normal.length < 1e-6:
        return fallback
    return normal.normalized().cross(first.normalized()).normalized()

def body_axes(pos):
    up = safe_dir(pos.get("pelvis", Vector((0, 0, 0))), pos.get("neck_01", pos.get("spine_03", Vector((0, 0, 1)))), Vector((0, 0, 1)))
    if "upperarm_l" in pos and "upperarm_r" in pos:
        right = safe_dir(pos["upperarm_r"], pos["upperarm_l"], Vector((1, 0, 0)))
    elif "thigh_l" in pos and "thigh_r" in pos:
        right = safe_dir(pos["thigh_r"], pos["thigh_l"], Vector((1, 0, 0)))
    else:
        right = Vector((1, 0, 0))
    forward = right.cross(up)
    if forward.length < 1e-6:
        forward = Vector((0, 1, 0))
    return up.normalized(), right.normalized(), forward.normalized()

def basis_for_bone(pos, bone):
    tail = TAIL_TARGETS.get(bone)
    if not tail or bone not in pos or tail not in pos:
        return None
    forward = pos[tail] - pos[bone]
    body_up, body_right, body_forward = body_axes(pos)
    global_up = Vector((0, 0, 1))

    if bone in ("root",):
        return basis_from_forward_up(Vector((0, 0, 1)), body_forward, global_up)
    if bone in ("pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head"):
        return basis_from_forward_up(forward, body_forward, global_up)
    if bone in ("upperarm_l", "lowerarm_l"):
        hint = plane_hint(pos, "upperarm_l", "lowerarm_l", "hand_l", body_up)
        return basis_from_forward_up(forward, hint, body_up)
    if bone == "hand_l":
        return basis_from_forward_up(forward, body_up, global_up)
    if bone in ("upperarm_r", "lowerarm_r"):
        hint = plane_hint(pos, "upperarm_r", "lowerarm_r", "hand_r", body_up)
        return basis_from_forward_up(forward, hint, body_up)
    if bone == "hand_r":
        return basis_from_forward_up(forward, body_up, global_up)
    if bone in ("thigh_l", "calf_l"):
        hint = plane_hint(pos, "thigh_l", "calf_l", "foot_l", body_forward)
        return basis_from_forward_up(forward, hint, body_forward)
    if bone == "foot_l":
        return basis_from_forward_up(forward, global_up, body_forward)
    if bone in ("thigh_r", "calf_r"):
        hint = plane_hint(pos, "thigh_r", "calf_r", "foot_r", body_forward)
        return basis_from_forward_up(forward, hint, body_forward)
    if bone == "foot_r":
        return basis_from_forward_up(forward, global_up, body_forward)
    return basis_from_forward_up(forward, global_up, body_forward)

def smooth_quat(previous, current, alpha):
    if previous is None:
        return current.copy()
    cur = current.copy()
    if previous.dot(cur) < 0:
        cur.negate()
    return previous.slerp(cur, alpha)

def smooth_positions(raw_frames, alpha=0.45, max_step=1.15):
    smoothed = []
    previous = None
    for raw in raw_frames:
        if previous is None:
            current = {name: value.copy() for name, value in raw.items()}
        else:
            current = {}
            for name, value in raw.items():
                prev = previous.get(name, value)
                candidate = prev.lerp(value, alpha)
                delta = candidate - prev
                if delta.length > max_step:
                    candidate = prev + delta.normalized() * max_step
                current[name] = candidate
        smoothed.append(current)
        previous = current
    return smoothed

def bone_lengths_from_motion(pos):
    lengths = {}
    for a, b in (
        ("upperarm_l", "lowerarm_l"), ("lowerarm_l", "hand_l"),
        ("upperarm_r", "lowerarm_r"), ("lowerarm_r", "hand_r"),
        ("thigh_l", "calf_l"), ("calf_l", "foot_l"),
        ("thigh_r", "calf_r"), ("calf_r", "foot_r"),
    ):
        if a in pos and b in pos:
            lengths[(a, b)] = max((pos[b] - pos[a]).length, 0.05)
    return lengths

def clamp(value, low, high):
    return max(low, min(high, value))

def solve_hinge_mid(pos, root, mid, end, lengths, previous_plane, fallback_plane):
    if root not in pos or mid not in pos or end not in pos:
        return previous_plane
    l1 = lengths.get((root, mid), (pos[mid] - pos[root]).length)
    l2 = lengths.get((mid, end), (pos[end] - pos[mid]).length)
    start = pos[root]
    finish = pos[end]
    axis = finish - start
    dist = axis.length
    if dist < 1e-6:
        return previous_plane
    max_reach = max(l1 + l2 - 1e-4, 0.05)
    min_reach = abs(l1 - l2) + 1e-4
    if dist > max_reach:
        finish = start + axis.normalized() * max_reach
        pos[end] = finish
        axis = finish - start
        dist = axis.length
    if dist < min_reach:
        finish = start + axis.normalized() * min_reach
        pos[end] = finish
        axis = finish - start
        dist = axis.length

    axis_dir = axis.normalized()
    current_plane = pos[mid] - (start + axis_dir * (pos[mid] - start).dot(axis_dir))
    if current_plane.length < 1e-6:
        current_plane = previous_plane if previous_plane is not None else fallback_plane
    current_plane = projected_axis(current_plane, axis_dir, fallback_plane)
    if previous_plane is not None and current_plane.dot(previous_plane) < 0:
        current_plane.negate()

    x = clamp((l1 * l1 - l2 * l2 + dist * dist) / (2.0 * dist), 0.0, dist)
    h2 = max(l1 * l1 - x * x, 0.0)
    h = h2 ** 0.5
    pos[mid] = start + axis_dir * x + current_plane * h
    return current_plane.copy()

def stabilize_motion(raw_positions):
    smoothed = smooth_positions(raw_positions, alpha=0.42, max_step=0.9)
    if not smoothed:
        return smoothed
    lengths = bone_lengths_from_motion(smoothed[0])
    previous_planes = {
        "left_arm": None,
        "right_arm": None,
        "left_leg": None,
        "right_leg": None,
    }
    out = []
    previous_pelvis = None
    for pos in smoothed:
        pos = {name: value.copy() for name, value in pos.items()}
        body_up, body_right, body_forward = body_axes(pos)

        previous_planes["left_arm"] = solve_hinge_mid(
            pos, "upperarm_l", "lowerarm_l", "hand_l", lengths, previous_planes["left_arm"], body_up
        )
        previous_planes["right_arm"] = solve_hinge_mid(
            pos, "upperarm_r", "lowerarm_r", "hand_r", lengths, previous_planes["right_arm"], body_up
        )
        previous_planes["left_leg"] = solve_hinge_mid(
            pos, "thigh_l", "calf_l", "foot_l", lengths, previous_planes["left_leg"], body_forward
        )
        previous_planes["right_leg"] = solve_hinge_mid(
            pos, "thigh_r", "calf_r", "foot_r", lengths, previous_planes["right_leg"], body_forward
        )

        for foot, toe in (("foot_l", "foot_l_tip"), ("foot_r", "foot_r_tip")):
            if foot in pos:
                forward = projected_axis(body_forward, Vector((0, 0, 1)), Vector((0, 1, 0)))
                if toe in pos:
                    current = projected_axis(pos[toe] - pos[foot], Vector((0, 0, 1)), forward)
                    if current.dot(forward) > 0:
                        forward = current
                pos[toe] = pos[foot] + forward * 0.25

        for hand, tip, elbow in (("hand_l", "hand_l_tip", "lowerarm_l"), ("hand_r", "hand_r_tip", "lowerarm_r")):
            if hand in pos and elbow in pos:
                pos[tip] = pos[hand] + safe_dir(pos[elbow], pos[hand], body_right) * 0.2

        if previous_pelvis is not None and "pelvis" in pos:
            pos["pelvis"] = previous_pelvis.lerp(pos["pelvis"], 0.55)
        if "pelvis" in pos:
            previous_pelvis = pos["pelvis"].copy()
        out.append(pos)
    return out

def import_fbx(path):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.import_scene.fbx(filepath=str(path))

def find_armature():
    arms = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if not arms:
        raise RuntimeError("Imported Knight FBX contains no armature")
    # Prefer the armature with the requested bones.
    for arm in arms:
        names = {b.name for b in arm.data.bones}
        if "pelvis" in names and "spine_03" in names and "upperarm_l" in names:
            return arm
    return arms[0]

def rest_world_bases(arm):
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    rest_pos = {}
    parent_by_bone = {}
    for bone_name in SOLVED_BONES:
        if bone_name not in arm.pose.bones:
            continue
        pb = arm.pose.bones[bone_name]
        rest_pos[bone_name] = pb.head.copy()
        tail_name = TAIL_TARGETS.get(bone_name)
        if tail_name and tail_name not in rest_pos:
            rest_pos[tail_name] = pb.tail.copy()
        parent_by_bone[bone_name] = pb.parent.name if pb.parent else None
    bases = {}
    for bone_name in SOLVED_BONES:
        basis = basis_for_bone(rest_pos, bone_name)
        if basis is not None:
            bases[bone_name] = basis
    return bases, parent_by_bone

def clear_existing_animation(arm):
    arm.animation_data_clear()
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            obj.animation_data_clear()

import_fbx(KNIGHT_FBX)
arm = find_armature()
arm.name = "SK_Knight4_Animated_Armature"
arm.location = (0, 0, 0)
arm.rotation_euler = (0, 0, 0)
arm.scale = (1, 1, 1)

bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = len(FRAMES)
bpy.context.scene.render.fps = int(round(FPS))

clear_existing_animation(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="POSE")
for pb in arm.pose.bones:
    pb.rotation_mode = "QUATERNION"
    pb.location = (0, 0, 0)
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.scale = (1, 1, 1)

rest_bases, parent_by_bone = rest_world_bases(arm)
previous_quats = {}
extremity_bones = {"hand_l", "hand_r", "foot_l", "foot_r", "lowerarm_l", "lowerarm_r", "calf_l", "calf_r"}
raw_motion_positions = [ue_motion_points(normalized_points(frame)) for frame in FRAMES]
stable_motion_positions = stabilize_motion(raw_motion_positions)

for frame_idx, pos in enumerate(stable_motion_positions, start=1):
    bpy.context.scene.frame_set(frame_idx)
    target_bases = {}
    world_deltas = {}
    local_quats = {}

    for bone_name in SOLVED_BONES:
        if bone_name not in arm.pose.bones:
            continue
        if bone_name == "root":
            world_deltas[bone_name] = Matrix.Identity(3)
            local_quats[bone_name] = world_deltas[bone_name].to_quaternion()
            continue
        target_basis = basis_for_bone(pos, bone_name)
        rest_basis = rest_bases.get(bone_name)
        if target_basis is None or rest_basis is None:
            world_deltas[bone_name] = Matrix.Identity(3)
        else:
            world_deltas[bone_name] = target_basis @ rest_basis.inverted()

        parent_name = parent_by_bone.get(bone_name)
        parent_delta = world_deltas.get(parent_name, Matrix.Identity(3))
        local_delta = parent_delta.inverted() @ world_deltas[bone_name]
        quat = local_delta.to_quaternion()
        alpha = 0.35 if bone_name in extremity_bones else 0.65
        quat = smooth_quat(previous_quats.get(bone_name), quat, alpha)
        previous_quats[bone_name] = quat.copy()
        local_quats[bone_name] = quat

    for bone_name in SOLVED_BONES:
        if bone_name not in arm.pose.bones:
            continue
        pb = arm.pose.bones[bone_name]
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
        pb.rotation_quaternion = local_quats.get(bone_name, Matrix.Identity(3).to_quaternion())
        pb.keyframe_insert(data_path="rotation_quaternion", frame=frame_idx)
        pb.keyframe_insert(data_path="scale", frame=frame_idx)

        if bone_name in ("root", "pelvis"):
            pb.keyframe_insert(data_path="location", frame=frame_idx)

bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
for obj in bpy.data.objects:
    if obj.type == "MESH":
        obj.select_set(True)
bpy.context.view_layer.objects.active = arm

for action in bpy.data.actions:
    action.name = "RTMPose_Test_Anim_Knight4"

blend_path = BASE / "OctopiDummy_SK_Knight4_anim.blend"
fbx_path = BASE / "OctopiDummy_SK_Knight4_anim.fbx"
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
)
print(f"Saved {blend_path}")
print(f"Saved {fbx_path}")
'''
    script_path.write_text(
        script.replace("__BASE__", str(folder)).replace("__KNIGHT_FBX__", str(knight_fbx)).strip() + "\n",
        encoding="utf-8",
    )
    return script_path


def main():
    args = parse_args()
    folder = Path(args.folder).resolve()
    knight_fbx = Path(args.knight_fbx).resolve()
    if not (folder / "skeleton_animation.json").exists():
        raise FileNotFoundError(folder / "skeleton_animation.json")
    if not knight_fbx.exists():
        raise FileNotFoundError(
            f"Missing Knight4 bind-pose FBX: {knight_fbx}. "
            "Run UnrealTools/export_sk_knight4_bind_fbx.py inside Unreal first."
        )
    script = write_blender_script(folder, knight_fbx)
    subprocess.run([args.blender, "--background", "--python", str(script)], check=True)
    print(f"Knight4 animation FBX written to: {folder / 'OctopiDummy_SK_Knight4_anim.fbx'}")


if __name__ == "__main__":
    main()
