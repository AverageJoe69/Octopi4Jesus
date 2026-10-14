import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


COCO17_NAMES = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]

LEFT_RIGHT_PAIRS = [
    ("left_eye", "right_eye"),
    ("left_ear", "right_ear"),
    ("left_shoulder", "right_shoulder"),
    ("left_elbow", "right_elbow"),
    ("left_wrist", "right_wrist"),
    ("left_hip", "right_hip"),
    ("left_knee", "right_knee"),
    ("left_ankle", "right_ankle"),
]

EDGES = [
    ("pelvis", "left_hip"),
    ("pelvis", "right_hip"),
    ("pelvis", "neck"),
    ("neck", "left_shoulder"),
    ("neck", "right_shoulder"),
    ("neck", "nose"),
    ("nose", "left_eye"),
    ("nose", "right_eye"),
    ("left_eye", "left_ear"),
    ("right_eye", "right_ear"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
]

TREE_EDGES = [
    ("pelvis", "neck"),
    ("neck", "nose"),
    ("nose", "left_eye"),
    ("left_eye", "left_ear"),
    ("nose", "right_eye"),
    ("right_eye", "right_ear"),
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

HIERARCHY = {
    "pelvis": ["left_hip", "right_hip", "neck"],
    "neck": ["left_shoulder", "right_shoulder", "nose"],
    "nose": ["left_eye", "right_eye"],
    "left_eye": ["left_ear"],
    "right_eye": ["right_ear"],
    "left_shoulder": ["left_elbow"],
    "left_elbow": ["left_wrist"],
    "right_shoulder": ["right_elbow"],
    "right_elbow": ["right_wrist"],
    "left_hip": ["left_knee"],
    "left_knee": ["left_ankle"],
    "right_hip": ["right_knee"],
    "right_knee": ["right_ankle"],
}


def parse_args():
    parser = argparse.ArgumentParser(description="Export RTMPose triangulated skeleton sequence for Blender")
    parser.add_argument("--input", default="outputs/moveai_style_rtmpose_anim")
    parser.add_argument("--out", default="outputs/moveai_style_rtmpose_anim/blender_export")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--constraint-clean", default="true")
    parser.add_argument("--lock-bone-lengths", default="false")
    parser.add_argument("--constraint-window", type=int, default=5)
    parser.add_argument("--max-joint-step-m", type=float, default=0.25)
    parser.add_argument("--max-bone-angle-deg", type=float, default=45.0)
    parser.add_argument("--bone-length-iters", type=int, default=4)
    parser.add_argument("--fix-side-swaps", default="true")
    parser.add_argument("--body-side-gate", default="true")
    parser.add_argument("--arm-ik", default="true")
    parser.add_argument("--arm-wrist-max-step-m", type=float, default=0.35)
    parser.add_argument("--arm-target-blend", type=float, default=0.35)
    parser.add_argument("--outlier-clean", default="true")
    parser.add_argument("--outlier-window", type=int, default=5)
    parser.add_argument("--outlier-threshold-m", type=float, default=0.45)
    parser.add_argument("--max-reproj-error-px", type=float, default=18.0)
    parser.add_argument("--min-joint-confidence", type=float, default=0.35)
    parser.add_argument(
        "--coordinate-mode",
        default="bvh_blender",
        choices=["unreal", "blender", "bvh_blender"],
        help=(
            "blender converts Unreal left-handed XYZ to direct Blender X,-Y,Z. "
            "bvh_blender writes Y-up BVH coordinates so Blender's BVH importer lands upright."
        ),
    )
    return parser.parse_args()


def str_to_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def frame_dirs(root):
    dirs = sorted(Path(root).glob("frame*"))
    return [d for d in dirs if (d / "skeleton_3d.json").exists()]


def load_frame(path, min_confidence=0.0, max_reproj_error=float("inf")):
    data = json.loads((path / "skeleton_3d.json").read_text(encoding="utf-8"))
    joints = {}
    for name, item in data["joints"].items():
        confidence = float(item.get("confidence", 1.0))
        error = float(item.get("mean_reprojection_error_px", 0.0))
        if confidence < min_confidence or error > max_reproj_error:
            continue
        joints[name] = np.asarray(item["world_m"], dtype=np.float64)
    if "left_hip" in joints and "right_hip" in joints:
        joints["pelvis"] = 0.5 * (joints["left_hip"] + joints["right_hip"])
    if "left_shoulder" in joints and "right_shoulder" in joints:
        joints["neck"] = 0.5 * (joints["left_shoulder"] + joints["right_shoulder"])
    return joints


def convert_coords(point, mode):
    point = np.asarray(point, dtype=np.float64)
    if mode == "blender":
        return np.array([point[0], -point[1], point[2]], dtype=np.float64)
    if mode == "bvh_blender":
        # Blender's BVH importer assumes BVH data is Y-up and converts it to
        # Blender Z-up. Put Unreal height on BVH Y so it arrives upright.
        return np.array([point[0], point[2], -point[1]], dtype=np.float64)
    return point


def load_sequence(root, scale, coordinate_mode, min_confidence=0.0, max_reproj_error=float("inf")):
    frames = []
    names = []
    for path in frame_dirs(root):
        frame = load_frame(path, min_confidence=min_confidence, max_reproj_error=max_reproj_error)
        frames.append({k: convert_coords(v * scale, coordinate_mode) for k, v in frame.items()})
        names.append(path.name)
    if not frames:
        raise FileNotFoundError(f"No skeleton_3d.json files found under {root}")
    return names, frames


def complete_frames(frames):
    all_joints = set(["pelvis", "neck", *COCO17_NAMES])
    previous = {}
    completed = []
    for frame in frames:
        current = dict(previous)
        current.update(frame)
        for joint in all_joints:
            if joint not in current:
                current[joint] = np.zeros(3, dtype=np.float64)
        completed.append(current)
        previous = current
    return completed


def fix_side_swaps(frames):
    if not frames:
        return frames
    fixed = [dict(frames[0])]
    for idx in range(1, len(frames)):
        prev = fixed[-1]
        cur = dict(frames[idx])
        for left, right in LEFT_RIGHT_PAIRS:
            if left not in cur or right not in cur or left not in prev or right not in prev:
                continue
            same = float(np.linalg.norm(cur[left] - prev[left]) + np.linalg.norm(cur[right] - prev[right]))
            swapped = float(np.linalg.norm(cur[right] - prev[left]) + np.linalg.norm(cur[left] - prev[right]))
            if swapped + 1e-9 < same:
                cur[left], cur[right] = cur[right], cur[left]
        fixed.append(cur)
    return fixed


def outlier_hold_frames(frames, window, threshold):
    if threshold <= 0 or len(frames) < 3:
        return frames
    joints = sorted(frames[0].keys())
    out = [dict(frame) for frame in frames]
    radius = max(1, int(window) // 2)
    for idx in range(1, len(frames) - 1):
        start = max(0, idx - radius)
        end = min(len(frames), idx + radius + 1)
        for joint in joints:
            values = np.asarray([frames[i][joint] for i in range(start, end)], dtype=np.float64)
            median = np.median(values, axis=0)
            if float(np.linalg.norm(frames[idx][joint] - median)) > threshold:
                out[idx][joint] = out[idx - 1][joint].copy()
    return out


def torso_right_axis(frame):
    if "left_shoulder" in frame and "right_shoulder" in frame:
        axis = frame["right_shoulder"] - frame["left_shoulder"]
    elif "left_hip" in frame and "right_hip" in frame:
        axis = frame["right_hip"] - frame["left_hip"]
    else:
        return None
    norm = float(np.linalg.norm(axis))
    if norm <= 1e-9:
        return None
    return axis / norm


def torso_center(frame):
    parts = [name for name in ("left_shoulder", "right_shoulder", "left_hip", "right_hip") if name in frame]
    if not parts:
        return None
    return np.mean([frame[name] for name in parts], axis=0)


def body_side_hold_frames(frames):
    if len(frames) < 2:
        return frames
    out = [dict(frames[0])]
    left_joints = {"left_shoulder", "left_elbow", "left_wrist", "left_hip", "left_knee", "left_ankle"}
    right_joints = {"right_shoulder", "right_elbow", "right_wrist", "right_hip", "right_knee", "right_ankle"}
    for idx in range(1, len(frames)):
        prev = out[-1]
        cur = dict(frames[idx])
        axis = torso_right_axis(prev)
        center = torso_center(prev)
        if axis is None or center is None:
            out.append(cur)
            continue
        for joint in left_joints | right_joints:
            if joint not in cur or joint not in prev:
                continue
            side = float(np.dot(cur[joint] - center, axis))
            prev_side = float(np.dot(prev[joint] - center, axis))
            if joint in left_joints and side > 0.05 and prev_side < 0.15:
                cur[joint] = prev[joint].copy()
            if joint in right_joints and side < -0.05 and prev_side > -0.15:
                cur[joint] = prev[joint].copy()
        out.append(cur)
    return out


def median_filter_frames(frames, window):
    if window <= 1:
        return frames
    radius = max(1, int(window) // 2)
    joints = sorted(frames[0].keys())
    filtered = []
    for idx, frame in enumerate(frames):
        start = max(0, idx - radius)
        end = min(len(frames), idx + radius + 1)
        out = dict(frame)
        for joint in joints:
            values = np.asarray([frames[i][joint] for i in range(start, end)], dtype=np.float64)
            out[joint] = np.median(values, axis=0)
        filtered.append(out)
    return filtered


def compute_template_lengths(frames):
    lengths = {}
    for parent, child in TREE_EDGES:
        values = []
        for frame in frames:
            if parent in frame and child in frame:
                length = float(np.linalg.norm(frame[child] - frame[parent]))
                if np.isfinite(length) and length > 1e-6:
                    values.append(length)
        if values:
            lengths[(parent, child)] = float(np.median(values))
    return lengths


def clamp_vector_angle(current, previous, max_angle_rad):
    current_norm = float(np.linalg.norm(current))
    previous_norm = float(np.linalg.norm(previous))
    if current_norm <= 1e-9 or previous_norm <= 1e-9:
        return current
    cur_dir = current / current_norm
    prev_dir = previous / previous_norm
    dot = float(np.clip(np.dot(prev_dir, cur_dir), -1.0, 1.0))
    angle = float(np.arccos(dot))
    if angle <= max_angle_rad:
        return current
    t = max_angle_rad / max(angle, 1e-9)
    blended = (1.0 - t) * prev_dir + t * cur_dir
    blended_norm = float(np.linalg.norm(blended))
    if blended_norm <= 1e-9:
        return previous / previous_norm * current_norm
    return blended / blended_norm * current_norm


def apply_velocity_limit(frame, previous, max_step):
    if previous is None or max_step <= 0:
        return frame
    out = {}
    for joint, point in frame.items():
        prev = previous.get(joint)
        if prev is None:
            out[joint] = point
            continue
        delta = point - prev
        dist = float(np.linalg.norm(delta))
        if dist > max_step:
            out[joint] = prev + delta / dist * max_step
        else:
            out[joint] = point
    return out


def apply_bone_direction_limit(frame, previous, max_angle_deg):
    if previous is None or max_angle_deg <= 0:
        return frame
    out = dict(frame)
    max_angle_rad = np.deg2rad(float(max_angle_deg))
    for parent, child in TREE_EDGES:
        if parent not in out or child not in out or parent not in previous or child not in previous:
            continue
        current_vec = out[child] - out[parent]
        previous_vec = previous[child] - previous[parent]
        out[child] = out[parent] + clamp_vector_angle(current_vec, previous_vec, max_angle_rad)
    return out


def enforce_bone_lengths(frame, lengths, iters):
    out = dict(frame)
    for _ in range(max(0, int(iters))):
        for parent, child in TREE_EDGES:
            if parent not in out or child not in out or (parent, child) not in lengths:
                continue
            vec = out[child] - out[parent]
            norm = float(np.linalg.norm(vec))
            target = lengths[(parent, child)]
            if norm <= 1e-9:
                continue
            out[child] = out[parent] + vec / norm * target
    return out


def perpendicular_component(vector, axis):
    axis_norm = float(np.linalg.norm(axis))
    if axis_norm <= 1e-9:
        return vector
    axis = axis / axis_norm
    return vector - axis * float(np.dot(vector, axis))


def solve_two_bone_ik(shoulder, wrist, previous_elbow, upper_len, lower_len, fallback_normal):
    shoulder = np.asarray(shoulder, dtype=np.float64)
    wrist = np.asarray(wrist, dtype=np.float64)
    target_vec = wrist - shoulder
    dist = float(np.linalg.norm(target_vec))
    if dist <= 1e-9:
        target_vec = np.array([1.0, 0.0, 0.0], dtype=np.float64)
        dist = 1e-9
    direction = target_vec / dist
    max_reach = max(1e-6, upper_len + lower_len * 0.98)
    min_reach = max(1e-6, abs(upper_len - lower_len) + 1e-4)
    clamped_dist = float(np.clip(dist, min_reach, max_reach))
    wrist = shoulder + direction * clamped_dist

    a = (upper_len * upper_len - lower_len * lower_len + clamped_dist * clamped_dist) / (2.0 * clamped_dist)
    h_sq = max(0.0, upper_len * upper_len - a * a)
    h = float(np.sqrt(h_sq))

    if previous_elbow is not None:
        bend = perpendicular_component(previous_elbow - shoulder, direction)
    else:
        bend = perpendicular_component(fallback_normal, direction)
    bend_norm = float(np.linalg.norm(bend))
    if bend_norm <= 1e-9:
        bend = perpendicular_component(np.array([0.0, 0.0, 1.0], dtype=np.float64), direction)
        bend_norm = float(np.linalg.norm(bend))
    if bend_norm <= 1e-9:
        bend = perpendicular_component(np.array([0.0, 1.0, 0.0], dtype=np.float64), direction)
        bend_norm = float(np.linalg.norm(bend))
    bend = bend / max(bend_norm, 1e-9)
    elbow = shoulder + direction * a + bend * h
    return elbow, wrist


def apply_arm_ik(frames, lengths, args):
    if not str_to_bool(args.arm_ik):
        return frames
    sides = ("left", "right")
    out = []
    previous = None
    fallback_normals = {}
    if frames:
        first = frames[0]
        for side in sides:
            shoulder = f"{side}_shoulder"
            elbow = f"{side}_elbow"
            wrist = f"{side}_wrist"
            if shoulder in first and elbow in first and wrist in first:
                fallback_normals[side] = perpendicular_component(first[elbow] - first[shoulder], first[wrist] - first[shoulder])
            else:
                fallback_normals[side] = np.array([0.0, 0.0, 1.0], dtype=np.float64)

    for frame in frames:
        current = dict(frame)
        for side in sides:
            shoulder_name = f"{side}_shoulder"
            elbow_name = f"{side}_elbow"
            wrist_name = f"{side}_wrist"
            if shoulder_name not in current or wrist_name not in current:
                continue
            upper = lengths.get((shoulder_name, elbow_name))
            lower = lengths.get((elbow_name, wrist_name))
            if not upper or not lower:
                continue
            shoulder = current[shoulder_name]
            wrist_target = current[wrist_name]
            prev_elbow = previous.get(elbow_name) if previous else None
            prev_wrist = previous.get(wrist_name) if previous else None
            if prev_wrist is not None:
                delta = wrist_target - prev_wrist
                dist = float(np.linalg.norm(delta))
                max_step = float(args.arm_wrist_max_step_m)
                if max_step > 0 and dist > max_step:
                    wrist_target = prev_wrist + delta / dist * max_step
                blend = float(np.clip(args.arm_target_blend, 0.0, 1.0))
                wrist_target = (1.0 - blend) * prev_wrist + blend * wrist_target
            elbow, wrist = solve_two_bone_ik(
                shoulder,
                wrist_target,
                prev_elbow,
                float(upper),
                float(lower),
                fallback_normals.get(side, np.array([0.0, 0.0, 1.0], dtype=np.float64)),
            )
            current[elbow_name] = elbow
            current[wrist_name] = wrist
        out.append(current)
        previous = current
    return out


def constraint_clean_frames(frames, args):
    if str_to_bool(args.fix_side_swaps):
        frames = fix_side_swaps(frames)
    if str_to_bool(args.body_side_gate):
        frames = body_side_hold_frames(frames)
    if str_to_bool(args.outlier_clean):
        frames = outlier_hold_frames(frames, args.outlier_window, args.outlier_threshold_m)
    if not str_to_bool(args.constraint_clean):
        return frames
    frames = median_filter_frames(frames, args.constraint_window)
    lengths = compute_template_lengths(frames)
    frames = apply_arm_ik(frames, lengths, args)
    cleaned = []
    previous = None
    for frame in frames:
        current = {joint: np.asarray(point, dtype=np.float64).copy() for joint, point in frame.items()}
        current = apply_velocity_limit(current, previous, args.max_joint_step_m)
        current = apply_bone_direction_limit(current, previous, args.max_bone_angle_deg)
        current = enforce_bone_lengths(current, lengths, args.bone_length_iters)
        cleaned.append(current)
        previous = current
    return cleaned


def bvh_name(name):
    return name.replace("_", "")


def write_bvh_joint(lines, joint, parent, first_frame, depth):
    indent = "  " * depth
    keyword = "ROOT" if parent is None else "JOINT"
    lines.append(f"{indent}{keyword} {bvh_name(joint)}")
    lines.append(f"{indent}{{")
    if parent is None:
        offset = np.zeros(3)
    else:
        offset = first_frame[joint] - first_frame[parent]
    lines.append(f"{indent}  OFFSET {offset[0]:.6f} {offset[1]:.6f} {offset[2]:.6f}")
    if parent is None:
        lines.append(f"{indent}  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation")
    else:
        lines.append(f"{indent}  CHANNELS 3 Zrotation Xrotation Yrotation")
    children = HIERARCHY.get(joint, [])
    if children:
        for child in children:
            write_bvh_joint(lines, child, joint, first_frame, depth + 1)
    else:
        lines.append(f"{indent}  End Site")
        lines.append(f"{indent}  {{")
        lines.append(f"{indent}    OFFSET 0.000000 0.050000 0.000000")
        lines.append(f"{indent}  }}")
    lines.append(f"{indent}}}")


def hierarchy_order(joint="pelvis"):
    order = [joint]
    for child in HIERARCHY.get(joint, []):
        order.extend(hierarchy_order(child))
    return order


def primary_child(joint):
    children = HIERARCHY.get(joint, [])
    if not children:
        return None
    preferred = {
        "pelvis": "neck",
        "neck": "nose",
        "nose": "left_eye",
        "left_shoulder": "left_elbow",
        "left_elbow": "left_wrist",
        "right_shoulder": "right_elbow",
        "right_elbow": "right_wrist",
        "left_hip": "left_knee",
        "left_knee": "left_ankle",
        "right_hip": "right_knee",
        "right_knee": "right_ankle",
    }
    return preferred.get(joint, children[0])


def rotation_between_vectors(source, target):
    source = np.asarray(source, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    source_norm = float(np.linalg.norm(source))
    target_norm = float(np.linalg.norm(target))
    if source_norm <= 1e-9 or target_norm <= 1e-9:
        return Rotation.identity()
    source = source / source_norm
    target = target / target_norm
    dot = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if dot > 0.999999:
        return Rotation.identity()
    if dot < -0.999999:
        axis = np.cross(source, np.array([1.0, 0.0, 0.0]))
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(source, np.array([0.0, 1.0, 0.0]))
        axis = axis / np.linalg.norm(axis)
        return Rotation.from_rotvec(axis * np.pi)
    axis = np.cross(source, target)
    axis = axis / np.linalg.norm(axis)
    angle = float(np.arccos(dot))
    return Rotation.from_rotvec(axis * angle)


def joint_world_rotation(joint, frame, rest_frame):
    child = primary_child(joint)
    if child is None or child not in frame or joint not in frame or child not in rest_frame or joint not in rest_frame:
        return Rotation.identity()
    rest_vec = rest_frame[child] - rest_frame[joint]
    cur_vec = frame[child] - frame[joint]
    return rotation_between_vectors(rest_vec, cur_vec)


def joint_local_rotation(joint, frame, rest_frame, world_rotations):
    world_rot = joint_world_rotation(joint, frame, rest_frame)
    parent = find_parent(joint)
    if parent is None:
        return world_rot
    parent_world = world_rotations.get(parent, Rotation.identity())
    return parent_world.inv() * world_rot


def bvh_euler_zxy(rot):
    # BVH channel order below is Zrotation Xrotation Yrotation.
    return rot.as_euler("zxy", degrees=True)


def write_bvh(path, frames, fps):
    lines = ["HIERARCHY"]
    write_bvh_joint(lines, "pelvis", None, frames[0], 0)
    order = hierarchy_order()
    lines.append("MOTION")
    lines.append(f"Frames: {len(frames)}")
    lines.append(f"Frame Time: {1.0 / fps:.8f}")
    rest = frames[0]
    for frame in frames:
        values = []
        world_rotations = {}
        for joint in order:
            parent = find_parent(joint)
            if parent is None:
                pos = frame[joint]
                rot = joint_local_rotation(joint, frame, rest, world_rotations)
                world_rotations[joint] = rot
                rz, rx, ry = bvh_euler_zxy(rot)
                values.extend([pos[0], pos[1], pos[2], rz, rx, ry])
            else:
                rot = joint_local_rotation(joint, frame, rest, world_rotations)
                world_rotations[joint] = world_rotations.get(parent, Rotation.identity()) * rot
                rz, rx, ry = bvh_euler_zxy(rot)
                values.extend([rz, rx, ry])
        lines.append(" ".join(f"{value:.6f}" for value in values))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def find_parent(joint):
    if joint == "pelvis":
        return None
    for parent, children in HIERARCHY.items():
        if joint in children:
            return parent
    return "pelvis"


def write_animation_json(path, frame_names, frames, fps):
    data = {
        "fps": fps,
        "coordinate_frame": "BVH Y-up for Blender import, metres after scale" if frames else "metres",
        "frames": [],
        "edges": EDGES,
    }
    for name, frame in zip(frame_names, frames):
        data["frames"].append({name_: frame[name_].tolist() for name_ in ["pelvis", "neck", *COCO17_NAMES] if name_ in frame} | {"frame": name})
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_blender_script(path):
    base_path = str(Path(path).resolve().parent)
    script = r'''
import json
from pathlib import Path

import bpy
from mathutils import Vector

BASE = Path(r"__BASE_PATH__")
DATA = json.loads((BASE / "skeleton_animation.json").read_text())
FPS = DATA.get("fps", 30)
EDGES = DATA["edges"]
FRAMES = DATA["frames"]

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()
bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = len(FRAMES)
bpy.context.scene.render.fps = int(FPS)

mat_joint = bpy.data.materials.new("RTMPose_Joints")
mat_joint.diffuse_color = (1.0, 0.35, 0.02, 1.0)
mat_bone = bpy.data.materials.new("RTMPose_Bones")
mat_bone.diffuse_color = (1.0, 0.75, 0.05, 1.0)

joints = sorted({key for frame in FRAMES for key in frame.keys() if key != "frame"})
objects = {}
for joint in joints:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.055, location=(0, 0, 0))
    obj = bpy.context.object
    obj.name = joint
    obj.data.materials.append(mat_joint)
    objects[joint] = obj

def set_obj_location(obj, co, frame_idx):
    obj.location = (co[0], co[1], co[2])
    obj.keyframe_insert(data_path="location", frame=frame_idx)

for idx, frame in enumerate(FRAMES, start=1):
    for joint, obj in objects.items():
        if joint in frame:
            set_obj_location(obj, frame[joint], idx)

bone_objs = []
for a, b in EDGES:
    if a not in objects or b not in objects:
        continue
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.025, depth=1.0, location=(0, 0, 0))
    obj = bpy.context.object
    obj.name = f"{a}_to_{b}"
    obj.data.materials.append(mat_bone)
    bone_objs.append((obj, a, b))

def set_bone_transform(obj, a_co, b_co, frame_idx):
    a_vec = Vector((a_co[0], a_co[1], a_co[2]))
    b_vec = Vector((b_co[0], b_co[1], b_co[2]))
    vec = b_vec - a_vec
    length = vec.length
    if length < 1e-6:
        return
    obj.location = a_vec + vec * 0.5
    obj.rotation_euler = vec.to_track_quat("Z", "Y").to_euler()
    obj.scale = (1.0, 1.0, length)
    obj.keyframe_insert(data_path="location", frame=frame_idx)
    obj.keyframe_insert(data_path="rotation_euler", frame=frame_idx)
    obj.keyframe_insert(data_path="scale", frame=frame_idx)

for idx, frame in enumerate(FRAMES, start=1):
    for obj, a, b in bone_objs:
        if a not in frame or b not in frame:
            continue
        set_bone_transform(obj, frame[a], frame[b], idx)

bpy.ops.wm.save_as_mainfile(filepath=str(BASE / "rtmpose_skeleton_animation.blend"))
bpy.ops.export_scene.fbx(filepath=str(BASE / "rtmpose_skeleton_animation.fbx"), use_selection=False)
print(f"Saved {BASE / 'rtmpose_skeleton_animation.blend'}")
print(f"Saved {BASE / 'rtmpose_skeleton_animation.fbx'}")
'''
    Path(path).write_text(script.replace("__BASE_PATH__", base_path).strip() + "\n", encoding="utf-8")


def main():
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    frame_names, frames = load_sequence(
        args.input,
        args.scale,
        args.coordinate_mode,
        min_confidence=args.min_joint_confidence,
        max_reproj_error=args.max_reproj_error_px,
    )
    frames = complete_frames(frames)
    frames = constraint_clean_frames(frames, args)
    if str_to_bool(args.lock_bone_lengths) and not str_to_bool(args.constraint_clean):
        lengths = compute_template_lengths(frames)
        frames = [enforce_bone_lengths(frame, lengths, args.bone_length_iters) for frame in frames]
    write_bvh(out / "rtmpose_skeleton_animation.bvh", frames, args.fps)
    write_animation_json(out / "skeleton_animation.json", frame_names, frames, args.fps)
    write_blender_script(out / "make_blender_fbx.py")
    print(f"frames: {len(frames)}")
    print(f"wrote: {out / 'rtmpose_skeleton_animation.bvh'}")
    print(f"wrote: {out / 'skeleton_animation.json'}")
    print(f"wrote: {out / 'make_blender_fbx.py'}")


if __name__ == "__main__":
    main()
