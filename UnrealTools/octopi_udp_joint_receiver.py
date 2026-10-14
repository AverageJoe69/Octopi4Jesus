"""
Octopi RTMPose joint viewer for Unreal Editor.

Default mode is local file playback. It does not require UE Play.

Run inside Unreal Python:

    exec(open(r"C:/OCTOPI_Pipeline/UnrealTools/octopi_udp_joint_receiver.py").read())

Optional command-line style use from Unreal's py command can pass:

    --mode file|udp --loop true|false --fps 60

The file player loads skeleton_animation.json directly, updates existing or new
OctopiJoint_* debug spheres, and draws skeleton lines every editor tick.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

import unreal


DEFAULT_INPUT = r"C:/OCTOPI_Pipeline/outputs/gold_mocap_full_217f_mesh_dummy_fbx/skeleton_animation.json"
HOST = "127.0.0.1"
PORT = 50505
SECONDS = 20.0
FPS = 60.0
LOOP = True
MODE = "file"
SPACE = "root_motion"

# The current gold skeleton_animation.json was exported with --scale 10, so one
# stream unit behaves like a decimetre. Unreal units are centimetres, therefore
# stream_unit * 10 lands at the correct actor scale. If the source is regenerated
# in true metres, set this to 100.
UNREAL_UNITS_PER_STREAM_UNIT = 10.0

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


def log(message):
    unreal.log(f"[OctopiJoints] {message}")


def str_to_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mode", default=MODE, choices=["file", "udp"])
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--loop", default=str(LOOP).lower())
    parser.add_argument("--fps", type=float, default=FPS)
    parser.add_argument("--space", default=SPACE, choices=["in_place", "root_motion", "raw"])
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--seconds", type=float, default=SECONDS)
    parser.add_argument("--scale", type=float, default=UNREAL_UNITS_PER_STREAM_UNIT)
    args, _unknown = parser.parse_known_args(sys.argv[1:])
    return args


def stop_existing_player():
    state = getattr(unreal, "_octopi_joint_player_state", None)
    if not state:
        return
    handle = state.get("tick_handle")
    if handle is not None:
        try:
            unreal.unregister_slate_post_tick_callback(handle)
            log("Stopped previous joint playback callback.")
        except Exception:
            pass
    setattr(unreal, "_octopi_joint_player_state", None)


def pause_octopi_json_playback():
    state = getattr(unreal, "_octopi_joint_player_state", None)
    if not state:
        log("No JSON playback is running.")
        return False
    state["paused"] = True
    log("Paused JSON playback.")
    return True


def resume_octopi_json_playback():
    state = getattr(unreal, "_octopi_joint_player_state", None)
    if not state:
        log("No JSON playback is running.")
        return False
    state["paused"] = False
    state["accum"] = 0.0
    log("Resumed JSON playback.")
    return True


def toggle_octopi_json_playback():
    state = getattr(unreal, "_octopi_joint_player_state", None)
    if not state:
        log("No JSON playback is running.")
        return False
    if state.get("paused", False):
        return resume_octopi_json_playback()
    return pause_octopi_json_playback()


def octopi_to_unreal_xyz(x, y, z, scale):
    # Stream/source is x=right, y=forward, z=up.
    # Unreal is x=forward, y=right, z=up.
    return unreal.Vector(float(y) * scale, float(x) * scale, float(z) * scale)


def packet_point_to_unreal(point, scale):
    return octopi_to_unreal_xyz(point["x"], point["y"], point["z"], scale)


def find_or_spawn_joint_actor(name):
    actor_name = f"OctopiJoint_{name}"
    editor = unreal.EditorLevelLibrary
    for actor in editor.get_all_level_actors():
        if actor.get_actor_label() == actor_name:
            return actor

    actor = editor.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    actor.set_actor_label(actor_name)
    mesh = unreal.load_asset("/Engine/BasicShapes/Sphere.Sphere")
    mat = unreal.load_asset("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial")
    comp = actor.static_mesh_component
    if mesh:
        comp.set_static_mesh(mesh)
    if mat:
        comp.set_material(0, mat)
    actor.set_actor_scale3d(unreal.Vector(0.08, 0.08, 0.08))
    return actor


def update_joint_actors(joint_positions, actors):
    for joint_name, location in joint_positions.items():
        actor = actors.get(joint_name)
        if actor is None:
            actor = find_or_spawn_joint_actor(joint_name)
            actors[joint_name] = actor
        actor.set_actor_location(location, False, False)


def draw_skeleton_lines(joint_positions):
    world = unreal.EditorLevelLibrary.get_editor_world()
    color = unreal.LinearColor(0.0, 0.85, 0.1, 1.0)
    for a, b in EDGES:
        if a not in joint_positions or b not in joint_positions:
            continue
        try:
            unreal.SystemLibrary.draw_debug_line(
                world,
                joint_positions[a],
                joint_positions[b],
                color,
                0.08,
                2.5,
            )
        except Exception:
            # Draw-debug availability differs by editor/version. The joint
            # markers are still the source of truth if line drawing is absent.
            return


def invalidate_viewports():
    for method_name in ("editor_invalidate_viewports", "redraw_all_viewports"):
        method = getattr(unreal.EditorLevelLibrary, method_name, None)
        if method:
            try:
                method()
                return
            except Exception:
                pass


def source_frame_to_positions(frame, scale, space):
    pelvis = frame.get("pelvis", [0.0, 0.0, 0.0])
    ankles = [frame[name][2] for name in ("left_ankle", "right_ankle") if name in frame]
    ground_z = min(ankles) if ankles else 0.0
    if space == "raw":
        origin = [0.0, 0.0, 0.0]
    elif space == "root_motion":
        # Keep the original horizontal movement, but floor-normalize height.
        origin = [0.0, 0.0, ground_z]
    else:
        # Locked-in-place preview: pelvis horizontal motion removed.
        origin = [pelvis[0], pelvis[1], ground_z]

    positions = {}
    for name in JOINTS:
        value = frame.get(name)
        if value is None:
            continue
        positions[name] = octopi_to_unreal_xyz(
            value[0] - origin[0],
            value[1] - origin[1],
            value[2] - origin[2],
            scale,
        )
    return positions


def load_file_frames(input_path, scale, space):
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    frames = data["frames"]
    fps = float(data.get("fps", FPS))
    positions = [source_frame_to_positions(frame, scale, space) for frame in frames]
    return positions, fps


def start_file_playback(args):
    stop_existing_player()
    frames, source_fps = load_file_frames(args.input, args.scale, args.space)
    fps = args.fps if args.fps > 0 else source_fps
    frame_interval = 1.0 / max(fps, 1e-6)

    state = {
        "frames": frames,
        "actors": {},
        "index": 0,
        "accum": 0.0,
        "frame_interval": frame_interval,
        "loop": str_to_bool(args.loop),
        "paused": False,
        "tick_handle": None,
    }

    def tick(delta_seconds):
        frames = state["frames"]
        if not frames:
            return
        if state.get("paused", False):
            positions = frames[state["index"]]
            draw_skeleton_lines(positions)
            invalidate_viewports()
            return

        state["accum"] += float(delta_seconds)
        advanced = False
        while state["accum"] >= state["frame_interval"]:
            state["accum"] -= state["frame_interval"]
            state["index"] += 1
            advanced = True
            if state["index"] >= len(frames):
                if state["loop"]:
                    state["index"] = 0
                else:
                    state["index"] = len(frames) - 1
                    handle = state.get("tick_handle")
                    if handle is not None:
                        unreal.unregister_slate_post_tick_callback(handle)
                        state["tick_handle"] = None
                    log("Playback finished.")
                    break

        positions = frames[state["index"]]
        update_joint_actors(positions, state["actors"])
        draw_skeleton_lines(positions)
        invalidate_viewports()

        if advanced or state["index"] == 0:
            log(f"Frame {state['index']}/{len(frames) - 1}")

    handle = unreal.register_slate_post_tick_callback(tick)
    state["tick_handle"] = handle
    setattr(unreal, "_octopi_joint_player_state", state)

    # Draw immediately so there is something visible before the first tick.
    update_joint_actors(frames[0], state["actors"])
    draw_skeleton_lines(frames[0])
    invalidate_viewports()

    log(f"Started file playback: {args.input}")
    log(f"Frames: {len(frames)}  fps: {fps:g}  loop: {state['loop']}  scale: {args.scale:g}  space: {args.space}")


def start_octopi_json_playback(
    input_path=DEFAULT_INPUT,
    fps=30.0,
    loop=True,
    space=SPACE,
    scale=UNREAL_UNITS_PER_STREAM_UNIT,
):
    """Callable entrypoint for other Unreal Python tools."""
    args = argparse.Namespace(
        input=input_path,
        fps=float(fps),
        loop=str(bool(loop)).lower(),
        space=space,
        scale=float(scale),
    )
    start_file_playback(args)


def reset_octopi_json_playback_to_zero():
    state = getattr(unreal, "_octopi_joint_player_state", None)
    if not state:
        return False
    state["index"] = 0
    state["accum"] = 0.0
    frames = state.get("frames", [])
    if frames:
        update_joint_actors(frames[0], state.get("actors", {}))
        draw_skeleton_lines(frames[0])
        invalidate_viewports()
    log("Reset JSON playback to frame 0.")
    return True


def run_udp_receiver(args):
    stop_existing_player()
    log(f"Listening for Octopi joint UDP on {args.host}:{args.port} for {args.seconds:g}s")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(0.25)
    actors = {}
    start = time.time()
    frames = 0
    last_frame = None
    try:
        while time.time() - start < args.seconds:
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                continue

            packet = json.loads(data.decode("utf-8"))
            if packet.get("type") != "octopi.rtmpose3d.frame":
                continue

            positions = {
                joint_name: packet_point_to_unreal(point, args.scale)
                for joint_name, point in packet.get("joints", {}).items()
            }
            update_joint_actors(positions, actors)
            draw_skeleton_lines(positions)
            invalidate_viewports()
            frames += 1
            last_frame = packet.get("frame")
            log(f"Frame {last_frame}")
    finally:
        sock.close()
    log(f"Done. Received {frames} packets. Last frame: {last_frame}")


def main():
    args = parse_args()
    if args.mode == "udp":
        run_udp_receiver(args)
    else:
        start_file_playback(args)


if not getattr(unreal, "_octopi_import_only", False):
    main()
