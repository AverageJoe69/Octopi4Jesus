"""
Sync launcher for comparing imported dummy animation with Octopi JSON joints.

Load once in Unreal Python:

    exec(open(r"C:/OCTOPI_Pipeline/UnrealTools/octopi_synced_compare.py").read())

Then run:

    run_octopi_synced_compare(fps=60)
    pause_octopi_synced_compare()
    play_octopi_synced_compare()
    toggle_octopi_synced_compare()
    stop_octopi_synced_compare()

This does not use Sequencer, baking, or Control Rig.
"""

from __future__ import annotations

import builtins
from pathlib import Path

import unreal


JOINT_PLAYER_SCRIPT = r"C:/OCTOPI_Pipeline/UnrealTools/octopi_udp_joint_receiver.py"
JSON_INPUT = r"C:/OCTOPI_Pipeline/outputs/gold_mocap_full_217f_mesh_dummy_fbx/skeleton_animation.json"
DUMMY_SOURCE_FPS = 60.0
DUMMY_NAME_HINTS = (
    "OctopiDummy_in_place",
    "OctopiDummy",
    "rtmpose",
    "dummy",
)


def _log(message):
    unreal.log(f"[OctopiSync] {message}")


def _warn(message):
    unreal.log_warning(f"[OctopiSync] {message}")


def _is_skeletal_mesh_actor(actor):
    try:
        return actor.get_class().get_name() == "SkeletalMeshActor"
    except Exception:
        return False


def _skeletal_component(actor):
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


def find_imported_dummy_actor(name_hint=None):
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    candidates = []
    hints = (name_hint,) if name_hint else DUMMY_NAME_HINTS
    hints = tuple(str(h).lower() for h in hints if h)

    for actor in actors:
        comp = _skeletal_component(actor)
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
        for hint in hints:
            if hint in haystack:
                score += 100
        if "octopi" in haystack:
            score += 50
        if "dummy" in haystack:
            score += 25
        if score > 0:
            candidates.append((score, label, actor, mesh_name))

    if not candidates:
        skeletal = []
        for actor in actors:
            comp = _skeletal_component(actor)
            if comp:
                skeletal.append(actor)
        if len(skeletal) == 1:
            actor = skeletal[0]
            _warn(f"No name match found; using only skeletal actor in level: {actor.get_actor_label()}")
            return actor
        labels = [actor.get_actor_label() for actor in skeletal]
        raise RuntimeError(f"Could not find imported dummy skeletal actor. Skeletal actors found: {labels}")

    candidates.sort(key=lambda item: (-item[0], item[1]))
    _log("Dummy actor candidates:")
    for score, label, _actor, mesh_name in candidates[:10]:
        _log(f"  score={score:03d} actor={label} mesh={mesh_name}")
    return candidates[0][2]


def _set_play_rate(target, play_rate, label):
    for method_name in ("set_play_rate", "set_rate_scale"):
        method = getattr(target, method_name, None)
        if not method:
            continue
        try:
            method(float(play_rate))
            _log(f"{label}.{method_name}({play_rate:g})")
            return True
        except Exception as exc:
            _warn(f"{label}.{method_name}({play_rate:g}) failed: {exc}")
    return False


def reset_and_play_skeletal_animation(actor, play_rate=1.0):
    comp = _skeletal_component(actor)
    if not comp:
        raise RuntimeError(f"Actor has no SkeletalMeshComponent: {actor.get_actor_label()}")

    # Make the component evaluate its assigned animation asset if one exists.
    try:
        comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    except Exception:
        pass

    _set_play_rate(comp, play_rate, actor.get_actor_label())

    for method_name, args in (
        ("set_position", (0.0, False)),
        ("set_playing", (True,)),
        ("play", (True,)),
    ):
        method = getattr(comp, method_name, None)
        if not method:
            continue
        try:
            method(*args)
            _log(f"{actor.get_actor_label()}.{method_name}{args}")
        except Exception as exc:
            _warn(f"{method_name}{args} failed on {actor.get_actor_label()}: {exc}")

    # If the actor/component has an AnimSingleNodeInstance, reset that too.
    try:
        inst = comp.get_anim_instance()
        if inst:
            _set_play_rate(inst, play_rate, "AnimInstance")
            for method_name, args in (
                ("set_position", (0.0, False)),
                ("set_playing", (True,)),
                ("play", (True,)),
            ):
                method = getattr(inst, method_name, None)
                if method:
                    try:
                        method(*args)
                        _log(f"AnimInstance.{method_name}{args}")
                    except Exception:
                        pass
    except Exception:
        pass

    try:
        comp.tick_animation(0.0, False)
        comp.refresh_bone_transforms()
    except Exception:
        pass

    return comp


def _set_skeletal_playing(actor, playing):
    comp = _skeletal_component(actor)
    if not comp:
        return False
    changed = False
    for method_name, args in (
        ("set_playing", (bool(playing),)),
        ("play", (True,)) if playing else ("stop", ()),
    ):
        method = getattr(comp, method_name, None)
        if not method:
            continue
        try:
            method(*args)
            changed = True
        except Exception as exc:
            _warn(f"{actor.get_actor_label()}.{method_name}{args} failed: {exc}")

    try:
        inst = comp.get_anim_instance()
        if inst:
            for method_name, args in (
                ("set_playing", (bool(playing),)),
                ("play", (True,)) if playing else ("stop", ()),
            ):
                method = getattr(inst, method_name, None)
                if method:
                    try:
                        method(*args)
                        changed = True
                    except Exception:
                        pass
    except Exception:
        pass
    return changed


def _load_joint_player_functions():
    # Prevent the joint player script from auto-starting while we import its
    # callable helpers into this Python context.
    setattr(unreal, "_octopi_import_only", True)
    namespace = {"__file__": JOINT_PLAYER_SCRIPT, "__name__": "octopi_joint_player_import"}
    try:
        exec(Path(JOINT_PLAYER_SCRIPT).read_text(encoding="utf-8"), namespace)
    finally:
        setattr(unreal, "_octopi_import_only", False)
    return namespace


def _joint_player_function(name):
    funcs = getattr(unreal, "_octopi_joint_player_functions", None)
    if not funcs:
        funcs = _load_joint_player_functions()
        setattr(unreal, "_octopi_joint_player_functions", funcs)
    return funcs.get(name)


def run_octopi_synced_compare(name_hint=None, fps=60.0, loop=True, dummy_source_fps=DUMMY_SOURCE_FPS):
    """Reset imported dummy animation and Octopi JSON joints to frame 0 together.

    fps controls both sides. The dummy FBX is assumed to have been imported at
    dummy_source_fps, so 60fps plays at rate 1.0 and 30fps plays at rate 0.5.
    """
    actor = find_imported_dummy_actor(name_hint)
    _log(f"Using dummy actor: {actor.get_actor_label()}")

    fps = float(fps)
    dummy_source_fps = float(dummy_source_fps) if dummy_source_fps else 60.0
    dummy_play_rate = fps / dummy_source_fps
    reset_and_play_skeletal_animation(actor, play_rate=dummy_play_rate)

    funcs = _load_joint_player_functions()
    setattr(unreal, "_octopi_joint_player_functions", funcs)
    start_playback = funcs["start_octopi_json_playback"]
    start_playback(
        input_path=JSON_INPUT,
        fps=float(fps),
        loop=bool(loop),
        space="root_motion",
        scale=10.0,
    )

    reset_func = funcs.get("reset_octopi_json_playback_to_zero")
    if reset_func:
        reset_func()

    _log(
        "Synced compare started at frame 0. "
        f"json_fps={fps:g} dummy_source_fps={dummy_source_fps:g} "
        f"dummy_play_rate={dummy_play_rate:g} loop={loop}"
    )
    setattr(
        unreal,
        "_octopi_synced_compare_state",
        {
            "actor": actor,
            "fps": fps,
            "loop": bool(loop),
            "dummy_source_fps": dummy_source_fps,
            "dummy_play_rate": dummy_play_rate,
            "paused": False,
        },
    )
    return actor


def pause_octopi_synced_compare():
    state = getattr(unreal, "_octopi_synced_compare_state", None)
    actor = state.get("actor") if state else None
    if actor:
        _set_skeletal_playing(actor, False)
    pause_json = _joint_player_function("pause_octopi_json_playback")
    if pause_json:
        pause_json()
    if state:
        state["paused"] = True
    _log("Paused synced compare.")


def play_octopi_synced_compare():
    state = getattr(unreal, "_octopi_synced_compare_state", None)
    actor = state.get("actor") if state else None
    if actor:
        _set_skeletal_playing(actor, True)
    resume_json = _joint_player_function("resume_octopi_json_playback")
    if resume_json:
        resume_json()
    if state:
        state["paused"] = False
    _log("Playing synced compare.")


def toggle_octopi_synced_compare():
    state = getattr(unreal, "_octopi_synced_compare_state", None)
    if state and state.get("paused", False):
        play_octopi_synced_compare()
    else:
        pause_octopi_synced_compare()


def stop_octopi_synced_compare():
    state = getattr(unreal, "_octopi_synced_compare_state", None)
    actor = state.get("actor") if state else None
    if actor:
        _set_skeletal_playing(actor, False)
    stop_json = _joint_player_function("stop_existing_player")
    if stop_json:
        stop_json()
    setattr(unreal, "_octopi_synced_compare_state", None)
    _log("Stopped synced compare.")


builtins.run_octopi_synced_compare = run_octopi_synced_compare
builtins.pause_octopi_synced_compare = pause_octopi_synced_compare
builtins.play_octopi_synced_compare = play_octopi_synced_compare
builtins.toggle_octopi_synced_compare = toggle_octopi_synced_compare
builtins.stop_octopi_synced_compare = stop_octopi_synced_compare
globals()["run_octopi_synced_compare"] = run_octopi_synced_compare
globals()["pause_octopi_synced_compare"] = pause_octopi_synced_compare
globals()["play_octopi_synced_compare"] = play_octopi_synced_compare
globals()["toggle_octopi_synced_compare"] = toggle_octopi_synced_compare
globals()["stop_octopi_synced_compare"] = stop_octopi_synced_compare
_log("Loaded. Run: run_octopi_synced_compare(), then play/pause/toggle/stop_octopi_synced_compare()")
