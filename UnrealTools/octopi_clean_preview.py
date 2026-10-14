"""
Clean Octopi/Knight preview.

Goal:
1. Open the Level Sequence that already plays the Knight.
2. Select/open the viewport you want to present.
3. Run this in Unreal Python:

    exec(open(r"C:/OCTOPI_Pipeline/UnrealTools/octopi_clean_preview.py").read())
    octopi_preview_start()

The script does not edit Sequencer. It starts the open Sequencer so the Knight
plays normally, then updates one clean Octopi joint dummy from
skeleton_animation.json using Sequencer's current frame as the master clock.
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import unreal


INPUT = r"C:/OCTOPI_Pipeline/outputs/gold_mocap_full_217f_mesh_dummy_fbx/skeleton_animation.json"
FPS = 60.0
LOOP = True
SPACE = "in_place"
SCALE = 10.0
PREVIEW_PREFIX = "OctopiPreview_"
OLD_PREFIXES = (
    "OctopiPreview_",
    "OctopiJoint_",
    "OctopiDummy_Compare",
    "OctopiDummy_SequencerCompare",
)

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
    unreal.log(f"[OctopiPreview] {message}")


def warn(message):
    unreal.log_warning(f"[OctopiPreview] {message}")


def _actor_subsystem():
    try:
        return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    except Exception:
        return None


def all_level_actors():
    subsystem = _actor_subsystem()
    if subsystem:
        try:
            return list(subsystem.get_all_level_actors())
        except Exception:
            pass
    return list(unreal.EditorLevelLibrary.get_all_level_actors())


def destroy_actor(actor):
    subsystem = _actor_subsystem()
    if subsystem:
        try:
            return subsystem.destroy_actor(actor)
        except Exception:
            pass
    return unreal.EditorLevelLibrary.destroy_actor(actor)


def spawn_actor(actor_class, location, rotation):
    subsystem = _actor_subsystem()
    if subsystem:
        try:
            return subsystem.spawn_actor_from_class(actor_class, location, rotation)
        except Exception:
            pass
    return unreal.EditorLevelLibrary.spawn_actor_from_class(actor_class, location, rotation)


def editor_world():
    try:
        return unreal.EditorLevelLibrary.get_editor_world()
    except Exception:
        return None


def game_world():
    for owner_name, method_name in (
        ("EditorLevelLibrary", "get_game_world"),
        ("UnrealEditorSubsystem", "get_game_world"),
    ):
        owner = getattr(unreal, owner_name, None)
        if not owner:
            continue
        try:
            if owner_name.endswith("Subsystem"):
                subsystem = unreal.get_editor_subsystem(owner)
                method = getattr(subsystem, method_name, None)
            else:
                method = getattr(owner, method_name, None)
            if method:
                world = method()
                if world:
                    return world
        except Exception:
            pass
    return None


def invalidate_viewports():
    for owner in (getattr(unreal, "EditorLevelLibrary", None), getattr(unreal, "EditorAssetLibrary", None)):
        if not owner:
            continue
        for method_name in ("editor_invalidate_viewports", "redraw_all_viewports"):
            method = getattr(owner, method_name, None)
            if method:
                try:
                    method()
                    return
                except Exception:
                    pass


def _stop_octopi_preview_clock():
    state = getattr(unreal, "_octopi_clean_preview_state", None)
    if state and state.get("tick_handle") is not None:
        try:
            unreal.unregister_slate_post_tick_callback(state["tick_handle"])
            log("Stopped preview clock.")
        except Exception:
            pass
    setattr(unreal, "_octopi_clean_preview_state", None)

    # Also stop callbacks from older helper scripts, if they are still around.
    for attr in ("_octopi_joint_player_state", "_octopi_manual_anim_clock_state"):
        old = getattr(unreal, attr, None)
        handle = old.get("tick_handle") if isinstance(old, dict) else None
        if handle is not None:
            try:
                unreal.unregister_slate_post_tick_callback(handle)
                log(f"Stopped old callback: {attr}")
            except Exception:
                pass
        setattr(unreal, attr, None)


def cleanup_octopi_preview_actors():
    destroyed = 0
    for actor in list(all_level_actors()):
        try:
            label = actor.get_actor_label()
        except Exception:
            continue
        if any(label.startswith(prefix) for prefix in OLD_PREFIXES):
            destroy_actor(actor)
            destroyed += 1
    log(f"Cleaned preview actors: {destroyed}")


def octopi_to_unreal_xyz(x, y, z, scale):
    # Source is x=right, y=forward, z=up. Unreal is x=forward, y=right, z=up.
    return unreal.Vector(float(y) * scale, float(x) * scale, float(z) * scale)


def source_frame_to_positions(frame, scale, space):
    pelvis = frame.get("pelvis", [0.0, 0.0, 0.0])
    ankles = [frame[name][2] for name in ("left_ankle", "right_ankle") if name in frame]
    ground_z = min(ankles) if ankles else 0.0
    if space == "raw":
        origin = [0.0, 0.0, 0.0]
    elif space == "root_motion":
        origin = [0.0, 0.0, ground_z]
    else:
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


def load_positions(input_path, scale=SCALE, space=SPACE):
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    source_fps = float(data.get("fps", FPS))
    frames = [source_frame_to_positions(frame, scale, space) for frame in data["frames"]]
    return frames, source_fps


def load_raw_frames(input_path):
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    return data.get("frames", [])


def make_preview_joint_actors():
    mesh = unreal.load_asset("/Engine/BasicShapes/Sphere.Sphere")
    actors = {}
    for joint in JOINTS:
        actor = spawn_actor(unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        actor.set_actor_label(f"{PREVIEW_PREFIX}{joint}")
        comp = getattr(actor, "static_mesh_component", None)
        if comp and mesh:
            try:
                comp.set_static_mesh(mesh)
            except Exception:
                pass
        actor.set_actor_scale3d(unreal.Vector(0.055, 0.055, 0.055))
        actors[joint] = actor
    return actors


def update_preview_dummy(positions, actors, origin_offset, world_override=None):
    for joint, actor in actors.items():
        pos = positions.get(joint)
        if pos is None:
            continue
        actor.set_actor_location(pos + origin_offset, False, False)

    world = world_override or editor_world()
    if not world:
        return
    color = unreal.LinearColor(0.0, 1.0, 0.0, 1.0)
    for a, b in EDGES:
        if a not in positions or b not in positions:
            continue
        try:
            unreal.SystemLibrary.draw_debug_line(
                world,
                positions[a] + origin_offset,
                positions[b] + origin_offset,
                color,
                0.025,
                3.0,
            )
        except Exception:
            pass


def _fmt_point(frame, name):
    value = frame.get(name)
    if not value:
        return f"{name}=--"
    try:
        return f"{name}=({float(value[0]):+.2f},{float(value[1]):+.2f},{float(value[2]):+.2f})"
    except Exception:
        return f"{name}=--"


def draw_preview_hud(world, origin, idx, frame_count, elapsed, fps, start_frame_offset, space, scale, raw_frame):
    if not world:
        return
    lines = [
        "OCTOPI LIVE",
        f"frame {idx:03d}/{max(frame_count - 1, 0):03d}  t={elapsed:.2f}s  fps={fps:g}",
        f"sync {int(start_frame_offset):+d}f  {space}  scale={float(scale):g}",
        _fmt_point(raw_frame, "pelvis"),
        f"{_fmt_point(raw_frame, 'left_wrist')}  {_fmt_point(raw_frame, 'right_wrist')}",
    ]
    text = "\n".join(lines)
    location = origin + unreal.Vector(0.0, 0.0, 180.0)
    color = unreal.LinearColor(0.1, 1.0, 0.1, 1.0)

    # Signature varies a little across UE Python builds, so try compact forms.
    for args in (
        (world, location, text, None, color, 0.035, True),
        (world, location, text, None, color, 0.035),
        (world, location, text, None, color),
    ):
        try:
            unreal.SystemLibrary.draw_debug_string(*args)
            return
        except Exception:
            pass



def world_time_seconds(world):
    """Best-effort PIE/game elapsed time so preview uses the same clock as gameplay."""
    if not world:
        return None
    for method_name in ("get_time_seconds", "get_real_time_seconds", "get_audio_time_seconds", "get_delta_seconds"):
        method = getattr(world, method_name, None)
        if not method:
            continue
        try:
            value = float(method())
            if method_name == "get_delta_seconds":
                continue
            return value
        except Exception:
            pass
    try:
        return float(unreal.GameplayStatics.get_time_seconds(world))
    except Exception:
        pass
    return None

def runtime_knight_location(world):
    fallback = find_reference_location()
    if not world:
        return fallback
    try:
        actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    except Exception:
        return fallback

    candidates = []
    for actor in actors:
        try:
            name = actor.get_actor_label()
        except Exception:
            try:
                name = actor.get_name()
            except Exception:
                name = ""
        lowered = name.lower()
        if "octopi" in lowered:
            continue
        score = 0
        for hint in ("bp_character_base", "bp_knight", "knight", "character"):
            if hint in lowered:
                score += 100
        if score <= 0:
            continue
        try:
            candidates.append((score, name, actor.get_actor_location()))
        except Exception:
            pass
    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][2]
    return fallback


def level_sequence_editor():
    lib = getattr(unreal, "LevelSequenceEditorBlueprintLibrary", None)
    if not lib:
        raise RuntimeError("LevelSequenceEditorBlueprintLibrary is unavailable. Open the Level Sequence that plays the Knight.")
    return lib


def current_sequence():
    lib = level_sequence_editor()
    try:
        sequence = lib.get_current_level_sequence()
    except Exception:
        sequence = None
    if not sequence:
        raise RuntimeError("No open Level Sequence. Open the sequence that plays the Knight, then run octopi_preview_start().")
    return sequence


def scrub_sequencer_to_frame(frame_index, fps):
    lib = level_sequence_editor()
    frame_number = None
    frame_time = None
    try:
        frame_number = unreal.FrameNumber(int(frame_index))
    except Exception:
        pass
    try:
        frame_time = unreal.FrameTime(unreal.FrameNumber(int(frame_index)))
    except Exception:
        pass

    # Different UE builds expose slightly different functions here.
    attempts = [
        ("set_current_time", int(frame_index)),
        ("set_current_local_time", int(frame_index)),
        ("set_current_time_seconds", float(frame_index) / max(float(fps), 1e-6)),
    ]
    if frame_number is not None:
        attempts.extend([
            ("set_current_time", frame_number),
            ("set_current_local_time", frame_number),
        ])
    if frame_time is not None:
        attempts.extend([
            ("set_current_time", frame_time),
            ("set_current_local_time", frame_time),
        ])

    for method_name, arg in attempts:
        method = getattr(lib, method_name, None)
        if not method:
            continue
        try:
            method(arg)
            return True
        except Exception:
            pass
    return False


def pause_open_sequencer():
    lib = level_sequence_editor()
    for method_name in ("pause", "stop"):
        method = getattr(lib, method_name, None)
        if method:
            try:
                method()
                return
            except Exception:
                pass


def skeletal_component(actor):
    for attr in ("skeletal_mesh_component", "mesh", "mesh_component"):
        comp = getattr(actor, attr, None)
        if comp:
            return comp
    try:
        comps = actor.get_components_by_class(unreal.SkeletalMeshComponent)
        if comps:
            return comps[0]
    except Exception:
        pass
    return None


def selected_skeletal_actor():
    subsystem = _actor_subsystem()
    selected = []
    if subsystem:
        try:
            selected = list(subsystem.get_selected_level_actors())
        except Exception:
            pass
    if not selected:
        try:
            selected = list(unreal.EditorLevelLibrary.get_selected_level_actors())
        except Exception:
            pass
    for actor in selected:
        if skeletal_component(actor):
            return actor
    return None


def find_knight_actor():
    selected = selected_skeletal_actor()
    if selected:
        log(f"Using selected skeletal actor: {selected.get_actor_label()}")
        return selected

    candidates = []
    for actor in all_level_actors():
        comp = skeletal_component(actor)
        if not comp:
            continue
        label = actor.get_actor_label()
        mesh_name = ""
        try:
            mesh = comp.get_editor_property("skeletal_mesh")
            mesh_name = mesh.get_name() if mesh else ""
        except Exception:
            pass
        haystack = f"{label} {mesh_name}".lower()
        score = 0
        for hint in ("bp_character_base", "sk_knight4", "knight4", "knight"):
            if hint in haystack:
                score += 100
        if score > 0:
            candidates.append((score, label, actor))
    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1]))
        log(f"Using found Knight/reference actor: {candidates[0][1]}")
        return candidates[0][2]
    return None


def find_reference_location():
    actor = find_knight_actor()
    if actor:
        try:
            return actor.get_actor_location()
        except Exception:
            pass
    warn("No selected/found skeletal Knight actor; placing Octopi preview near world origin.")
    return unreal.Vector(0.0, 0.0, 0.0)


def play_open_sequencer():
    lib = level_sequence_editor()
    for method_name in ("play", "play_looping"):
        method = getattr(lib, method_name, None)
        if not method:
            continue
        try:
            method()
            log(f"Started Sequencer via {method_name}().")
            return True
        except Exception:
            pass
    warn("Could not start Sequencer from Python. Press Play in Sequencer; Octopi will follow if current-time reading works.")
    return False


def sequencer_frame_index(fallback_index, fps):
    lib = level_sequence_editor()
    for method_name in ("get_current_time", "get_current_local_time"):
        method = getattr(lib, method_name, None)
        if not method:
            continue
        try:
            value = method()
            if hasattr(value, "frame_number"):
                frame_number = value.frame_number
                if hasattr(frame_number, "value"):
                    return int(frame_number.value)
                return int(frame_number)
            if hasattr(value, "value"):
                return int(value.value)
            return int(value)
        except Exception:
            pass
    method = getattr(lib, "get_current_time_seconds", None)
    if method:
        try:
            return int(float(method()) * float(fps))
        except Exception:
            pass
    return int(fallback_index)


def octopi_preview_start(input_path=INPUT, fps=FPS, loop=LOOP, space=SPACE, scale=SCALE, offset_x=0.0, offset_y=120.0, offset_z=0.0):
    """Start a clean synced preview.

    Open the Knight Level Sequence first. Select the Knight before running if
    you want the Octopi dummy positioned beside it.
    """
    _stop_octopi_preview_clock()
    cleanup_octopi_preview_actors()
    current_sequence()

    frames, source_fps = load_positions(input_path, scale=scale, space=space)
    fps = float(fps or source_fps)
    actors = make_preview_joint_actors()
    base_location = find_reference_location()
    origin_offset = base_location + unreal.Vector(float(offset_x), float(offset_y), float(offset_z))

    state = {
        "frames": frames,
        "actors": actors,
        "fps": fps,
        "loop": bool(loop),
        "time": 0.0,
        "index": 0,
        "tick_handle": None,
        "origin_offset": origin_offset,
        "scrub_ok": True,
        "paused": False,
    }

    def tick(delta_seconds):
        if state.get("paused", False):
            return
        frames_local = state["frames"]
        if not frames_local:
            return
        state["time"] += float(delta_seconds)
        fallback_idx = int(state["time"] * state["fps"])
        idx = sequencer_frame_index(fallback_idx, state["fps"])
        if idx >= len(frames_local):
            if state["loop"]:
                idx = idx % len(frames_local)
            else:
                idx = len(frames_local) - 1
        if idx < 0:
            idx = 0
        state["index"] = idx

        update_preview_dummy(frames_local[idx], state["actors"], state["origin_offset"])
        invalidate_viewports()

    handle = unreal.register_slate_post_tick_callback(tick)
    state["tick_handle"] = handle
    setattr(unreal, "_octopi_clean_preview_state", state)

    update_preview_dummy(frames[0], actors, origin_offset)
    play_open_sequencer()
    invalidate_viewports()
    log(f"Started clean preview. frames={len(frames)} fps={fps:g} loop={loop} space={space}")
    log("Use octopi_preview_stop(), octopi_preview_pause(), octopi_preview_resume().")


def octopi_preview_pause():
    state = getattr(unreal, "_octopi_clean_preview_state", None)
    if state:
        state["paused"] = True


def octopi_preview_resume():
    state = getattr(unreal, "_octopi_clean_preview_state", None)
    if state:
        state["paused"] = False


def octopi_preview_stop():
    _stop_octopi_preview_clock()
    cleanup_octopi_preview_actors()


def octopi_preview_start_pie(input_path=INPUT, fps=FPS, loop=LOOP, space="root_motion", scale=SCALE, offset_x=0.0, offset_y=80.0, offset_z=-90.0, start_frame_offset=0, show_hud=True):
    """Preview Octopi while the Knight is driven by top-toolbar Play / PIE.

    Run this first, then press top-toolbar Play. The preview waits for the game
    world, captures the runtime Knight/character start position once, and draws
    Octopi root motion from that fixed start point.
    """
    _stop_octopi_preview_clock()
    cleanup_octopi_preview_actors()
    frames, source_fps = load_positions(input_path, scale=scale, space=space)
    raw_frames = load_raw_frames(input_path)
    fps = float(fps or source_fps)
    state = {
        "frames": frames,
        "raw_frames": raw_frames,
        "fps": fps,
        "loop": bool(loop),
        "time": 0.0,
        "start_world_time": None,
        "last_world_time": None,
        "index": 0,
        "tick_handle": None,
        "paused": False,
        "offset": unreal.Vector(float(offset_x), float(offset_y), float(offset_z)),
        "start_frame_offset": int(start_frame_offset),
        "show_hud": bool(show_hud),
        "space": str(space),
        "scale": float(scale),
        "base_location": None,
        "announced_wait": False,
    }

    def tick(delta_seconds):
        if state.get("paused", False):
            return
        world = game_world()
        if not world:
            if not state["announced_wait"]:
                log("Waiting for PIE/game world. Press top-toolbar Play; Octopi will appear beside the Knight.")
                state["announced_wait"] = True
            return

        world_time = world_time_seconds(world)
        if world_time is None:
            state["time"] += float(delta_seconds)
        else:
            if state["start_world_time"] is None:
                state["start_world_time"] = world_time
                state["last_world_time"] = world_time
                state["time"] = 0.0
                log(f"Captured PIE clock zero: {world_time:.3f}s")
            elif state["last_world_time"] is not None and world_time < state["last_world_time"]:
                state["start_world_time"] = world_time
                state["time"] = 0.0
                log(f"PIE clock reset detected; resyncing Octopi at {world_time:.3f}s")
            else:
                state["time"] = max(0.0, world_time - state["start_world_time"])
            state["last_world_time"] = world_time

        idx = int(state["time"] * state["fps"]) + state["start_frame_offset"]
        if idx >= len(state["frames"]):
            if state["loop"]:
                duration = len(state["frames"]) / max(float(state["fps"]), 1e-6)
                if duration > 0.0:
                    idx = idx % len(state["frames"])
                    if world_time is None:
                        state["time"] = idx / max(float(state["fps"]), 1e-6)
                else:
                    idx = 0
            else:
                idx = len(state["frames"]) - 1
        if idx < 0:
            idx = 0
        state["index"] = idx

        if state["base_location"] is None:
            state["base_location"] = runtime_knight_location(world)
            log(f"Captured PIE preview origin: {state['base_location']}")

        origin = state["base_location"] + state["offset"]
        update_preview_dummy(state["frames"][idx], {}, origin, world_override=world)
        if state.get("show_hud", False):
            raw_frame = state["raw_frames"][idx] if idx < len(state["raw_frames"]) else {}
            draw_preview_hud(
                world,
                origin,
                idx,
                len(state["frames"]),
                state["time"],
                state["fps"],
                state["start_frame_offset"],
                state["space"],
                state["scale"],
                raw_frame,
            )
        invalidate_viewports()

    handle = unreal.register_slate_post_tick_callback(tick)
    state["tick_handle"] = handle
    setattr(unreal, "_octopi_clean_preview_state", state)
    log(f"Started PIE preview watcher. frames={len(frames)} fps={fps:g} loop={loop} space={space} start_frame_offset={int(start_frame_offset)} show_hud={bool(show_hud)}")
    log("Now press top-toolbar Play if the Knight is not already moving.")


# Backward-friendly names for the Unreal Python console.
globals()["octopi_preview_start"] = octopi_preview_start
globals()["octopi_preview_start_pie"] = octopi_preview_start_pie
globals()["octopi_preview_stop"] = octopi_preview_stop
globals()["octopi_preview_pause"] = octopi_preview_pause
globals()["octopi_preview_resume"] = octopi_preview_resume
globals()["stop_octopi_preview"] = octopi_preview_stop
builtins.octopi_preview_start = octopi_preview_start
builtins.octopi_preview_start_pie = octopi_preview_start_pie
builtins.octopi_preview_stop = octopi_preview_stop
builtins.octopi_preview_pause = octopi_preview_pause
builtins.octopi_preview_resume = octopi_preview_resume
builtins.stop_octopi_preview = octopi_preview_stop
log("Loaded. Use octopi_preview_start_pie() for top-toolbar Play, or octopi_preview_start() for Sequencer.")

