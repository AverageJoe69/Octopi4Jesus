import argparse
import json
import math
import socket
import time
from pathlib import Path

import numpy as np


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

LEFT_RIGHT_PAIRS = [
    ("left_shoulder", "right_shoulder"),
    ("left_elbow", "right_elbow"),
    ("left_wrist", "right_wrist"),
    ("left_hip", "right_hip"),
    ("left_knee", "right_knee"),
    ("left_ankle", "right_ankle"),
]

TREE_EDGES = [
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


def parse_args():
    parser = argparse.ArgumentParser(description="Export or UDP-stream stable RTMPose 3D joints")
    parser.add_argument("--input", default="outputs/gold_mocap_full_217f_mesh_dummy_fbx/skeleton_animation.json")
    parser.add_argument("--out-jsonl", default="outputs/gold_mocap_full_217f_mesh_dummy_fbx/Octopi_rtmpose_joint_stream.jsonl")
    parser.add_argument("--out-manifest", default="outputs/gold_mocap_full_217f_mesh_dummy_fbx/Octopi_rtmpose_joint_stream_manifest.json")
    parser.add_argument("--udp", default="false", choices=["true", "false"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50505)
    parser.add_argument("--fps", type=float, default=0.0, help="0 means use source fps")
    parser.add_argument("--loop", default="false", choices=["true", "false"])
    parser.add_argument("--space", default="in_place", choices=["raw", "in_place", "root_motion"])
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--clean", default="true", choices=["true", "false"])
    parser.add_argument("--median-window", type=int, default=5)
    parser.add_argument("--max-joint-step", type=float, default=0.22)
    parser.add_argument("--max-bone-angle-deg", type=float, default=35.0)
    parser.add_argument("--bone-length-iters", type=int, default=10)
    parser.add_argument("--outlier-threshold", type=float, default=0.45)
    return parser.parse_args()


def vec3(value):
    return [float(value[0]), float(value[1]), float(value[2])]


def load_source(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data, data["frames"], float(data.get("fps", 60.0))


def frame_to_arrays(frame):
    out = {}
    for name in JOINTS:
        if name in frame:
            out[name] = np.asarray(vec3(frame[name]), dtype=np.float64)
    return out


def arrays_to_frame(arrays, template):
    out = dict(template)
    for name, point in arrays.items():
        out[name] = [float(point[0]), float(point[1]), float(point[2])]
    return out


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
            same = np.linalg.norm(cur[left] - prev[left]) + np.linalg.norm(cur[right] - prev[right])
            swapped = np.linalg.norm(cur[right] - prev[left]) + np.linalg.norm(cur[left] - prev[right])
            if swapped + 1e-9 < same:
                cur[left], cur[right] = cur[right], cur[left]
        fixed.append(cur)
    return fixed


def torso_axis(frame):
    if "left_shoulder" in frame and "right_shoulder" in frame:
        axis = frame["right_shoulder"] - frame["left_shoulder"]
    elif "left_hip" in frame and "right_hip" in frame:
        axis = frame["right_hip"] - frame["left_hip"]
    else:
        return None
    norm = np.linalg.norm(axis)
    if norm <= 1e-9:
        return None
    return axis / norm


def torso_center(frame):
    keys = [k for k in ("left_shoulder", "right_shoulder", "left_hip", "right_hip") if k in frame]
    if not keys:
        return None
    return np.mean([frame[k] for k in keys], axis=0)


def body_side_gate(frames):
    if len(frames) < 2:
        return frames
    left = {"left_shoulder", "left_elbow", "left_wrist", "left_hip", "left_knee", "left_ankle"}
    right = {"right_shoulder", "right_elbow", "right_wrist", "right_hip", "right_knee", "right_ankle"}
    out = [dict(frames[0])]
    for idx in range(1, len(frames)):
        prev = out[-1]
        cur = dict(frames[idx])
        axis = torso_axis(prev)
        center = torso_center(prev)
        if axis is None or center is None:
            out.append(cur)
            continue
        for joint in left | right:
            if joint not in cur or joint not in prev:
                continue
            side = float(np.dot(cur[joint] - center, axis))
            prev_side = float(np.dot(prev[joint] - center, axis))
            if joint in left and side > 0.05 and prev_side < 0.15:
                cur[joint] = prev[joint].copy()
            if joint in right and side < -0.05 and prev_side > -0.15:
                cur[joint] = prev[joint].copy()
        out.append(cur)
    return out


def median_filter(frames, window):
    if window <= 1 or not frames:
        return frames
    radius = max(1, int(window) // 2)
    joints = sorted({k for frame in frames for k in frame.keys()})
    out = []
    for idx, frame in enumerate(frames):
        start = max(0, idx - radius)
        end = min(len(frames), idx + radius + 1)
        filtered = dict(frame)
        for joint in joints:
            values = [frames[i][joint] for i in range(start, end) if joint in frames[i]]
            if values:
                filtered[joint] = np.median(np.asarray(values), axis=0)
        out.append(filtered)
    return out


def outlier_hold(frames, threshold):
    if threshold <= 0 or len(frames) < 3:
        return frames
    out = [dict(frames[0])]
    for idx in range(1, len(frames) - 1):
        cur = dict(frames[idx])
        for joint, point in list(cur.items()):
            if joint not in frames[idx - 1] or joint not in frames[idx + 1]:
                continue
            expected = 0.5 * (frames[idx - 1][joint] + frames[idx + 1][joint])
            if np.linalg.norm(point - expected) > threshold:
                cur[joint] = out[-1][joint].copy()
        out.append(cur)
    out.append(dict(frames[-1]))
    return out


def compute_lengths(frames):
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


def velocity_limit(frame, previous, max_step):
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


def clamp_vec_angle(current, previous, max_angle_rad):
    cur_len = float(np.linalg.norm(current))
    prev_len = float(np.linalg.norm(previous))
    if cur_len <= 1e-9 or prev_len <= 1e-9:
        return current
    cur_dir = current / cur_len
    prev_dir = previous / prev_len
    dot = float(np.clip(np.dot(cur_dir, prev_dir), -1.0, 1.0))
    angle = math.acos(dot)
    if angle <= max_angle_rad:
        return current
    t = max_angle_rad / max(angle, 1e-9)
    direction = (1.0 - t) * prev_dir + t * cur_dir
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-9:
        return previous / prev_len * cur_len
    return direction / norm * cur_len


def bone_direction_limit(frame, previous, max_angle_deg):
    if previous is None or max_angle_deg <= 0:
        return frame
    out = dict(frame)
    max_angle_rad = math.radians(max_angle_deg)
    for parent, child in TREE_EDGES:
        if parent not in out or child not in out or parent not in previous or child not in previous:
            continue
        current = out[child] - out[parent]
        prev = previous[child] - previous[parent]
        out[child] = out[parent] + clamp_vec_angle(current, prev, max_angle_rad)
    return out


def enforce_lengths(frame, lengths, iters):
    out = dict(frame)
    for _ in range(max(0, int(iters))):
        for parent, child in TREE_EDGES:
            if parent not in out or child not in out or (parent, child) not in lengths:
                continue
            vec = out[child] - out[parent]
            norm = float(np.linalg.norm(vec))
            if norm <= 1e-9:
                continue
            out[child] = out[parent] + vec / norm * lengths[(parent, child)]
    return out


def clean_frames(frames, args):
    arrays = [frame_to_arrays(frame) for frame in frames]
    arrays = fix_side_swaps(arrays)
    arrays = body_side_gate(arrays)
    arrays = outlier_hold(arrays, args.outlier_threshold)
    arrays = median_filter(arrays, args.median_window)
    lengths = compute_lengths(arrays)

    cleaned = []
    previous = None
    for frame in arrays:
        cur = {joint: point.copy() for joint, point in frame.items()}
        cur = velocity_limit(cur, previous, args.max_joint_step)
        cur = bone_direction_limit(cur, previous, args.max_bone_angle_deg)
        cur = enforce_lengths(cur, lengths, args.bone_length_iters)
        cleaned.append(cur)
        previous = cur

    return [arrays_to_frame(cleaned[idx], frames[idx]) for idx in range(len(frames))]


def normalize_frames(frames, space, scale):
    first = frames[0]
    base_pelvis = vec3(first.get("pelvis", [0.0, 0.0, 0.0]))
    ankles = [first[name][2] for name in ("left_ankle", "right_ankle") if name in first]
    ground_z = min(ankles) if ankles else 0.0

    packets = []
    for frame_index, frame in enumerate(frames):
        pelvis = vec3(frame.get("pelvis", base_pelvis))
        if space == "raw":
            origin = [0.0, 0.0, 0.0]
            root_motion = [0.0, 0.0, 0.0]
        else:
            origin = [pelvis[0], pelvis[1], ground_z]
            root_motion = [0.0, 0.0, 0.0]
            if space == "root_motion":
                root_motion = [
                    (pelvis[0] - base_pelvis[0]) * scale,
                    (pelvis[1] - base_pelvis[1]) * scale,
                    0.0,
                ]

        joints = {}
        for name in JOINTS:
            if name not in frame:
                continue
            value = vec3(frame[name])
            joints[name] = {
                "x": (value[0] - origin[0]) * scale,
                "y": (value[1] - origin[1]) * scale,
                "z": (value[2] - origin[2]) * scale,
                "confidence": float(frame.get(f"{name}_confidence", 1.0)),
            }

        packets.append(
            {
                "type": "octopi.rtmpose3d.frame",
                "version": 1,
                "frame": frame_index,
                "time": frame_index,
                "space": space,
                "root_motion": {"x": root_motion[0], "y": root_motion[1], "z": root_motion[2]},
                "joints": joints,
            }
        )
    return packets


def write_jsonl(path, packets):
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for packet in packets:
            f.write(json.dumps(packet, separators=(",", ":")) + "\n")
    return out


def write_manifest(path, source_path, packets, fps, space, scale):
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "type": "octopi.rtmpose3d.manifest",
        "version": 1,
        "source": str(Path(source_path).resolve()),
        "fps": fps,
        "frame_count": len(packets),
        "space": space,
        "scale": scale,
        "units": "metres",
        "joints": JOINTS,
        "edges": EDGES,
        "udp_default": {"host": "127.0.0.1", "port": 50505},
    }
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


def stream_udp(packets, host, port, fps, loop):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    delay = 1.0 / max(fps, 1e-6)
    target = (host, port)
    print(f"Streaming {len(packets)} frames to udp://{host}:{port} at {fps:g} fps")
    try:
        while True:
            start = time.perf_counter()
            for index, packet in enumerate(packets):
                packet = dict(packet)
                packet["sent_unix_time"] = time.time()
                data = json.dumps(packet, separators=(",", ":")).encode("utf-8")
                sock.sendto(data, target)
                next_time = start + (index + 1) * delay
                sleep_for = next_time - time.perf_counter()
                if sleep_for > 0:
                    time.sleep(sleep_for)
            if not loop:
                break
    except KeyboardInterrupt:
        print("Stopped UDP stream.")


def main():
    args = parse_args()
    source, frames, source_fps = load_source(args.input)
    fps = args.fps if args.fps > 0 else source_fps
    if args.max_frames > 0:
        frames = frames[: args.max_frames]
    if args.clean == "true":
        frames = clean_frames(frames, args)

    packets = normalize_frames(frames, args.space, args.scale)
    jsonl = write_jsonl(args.out_jsonl, packets)
    manifest = write_manifest(args.out_manifest, args.input, packets, fps, args.space, args.scale)
    print(f"Wrote JSONL stream: {jsonl}")
    print(f"Wrote stream manifest: {manifest}")
    print(f"Frames: {len(packets)}  fps: {fps:g}  space: {args.space}")

    if args.udp == "true":
        stream_udp(packets, args.host, args.port, fps, args.loop == "true")


if __name__ == "__main__":
    main()
