"""
Sync launcher for comparing the scene Knight actor with Octopi JSON joints.

Load once in Unreal Python:

    exec(open(r"C:/OCTOPI_Pipeline/UnrealTools/octopi_knight_synced_compare.py").read())

Then run:

    run_octopi_knight_compare(fps=60)
    run_octopi_knight_compare(name_hint="selected", fps=60)
    run_octopi_knight_compare(name_hint="selected", use_current_animation=True, fps=60)
    run_octopi_original_vs_dummy_compare(knight_hint="selected", fps=60)
    pause_octopi_knight_compare()
    play_octopi_knight_compare()
    toggle_octopi_knight_compare()
    stop_octopi_knight_compare()
    cleanup_octopi_joint_markers()
    print_octopi_knight_debug()

This targets the actual Knight/Knight4 skeletal actor in the level rather than
an imported OctopiDummy actor. It expects the Knight4 animation FBX to have been
imported into Unreal as an animation asset for SK_Knight4.
"""

from __future__ import annotations

import builtins
from pathlib import Path

import unreal


JOINT_PLAYER_SCRIPT = r"C:/OCTOPI_Pipeline/UnrealTools/octopi_udp_joint_receiver.py"
JSON_INPUT = r"C:/OCTOPI_Pipeline/outputs/gold_mocap_full_217f_mesh_dummy_fbx/skeleton_animation.json"
DUMMY_SOURCE_FPS = 60.0
KNIGHT_HINTS = ("SK_Knight4", "Knight4", "Knight")
DUMMY_HINTS = ("OctopiDummy_in_place", "OctopiDummy", "rtmpose", "dummy")
ANIM_HINTS = ("OctopiDummy_SK_Knight4_anim", "RTMPose_Test_Anim_Knight4", "Knight4_anim", "Octopi")
DUMMY_ANIM_HINTS = ("OctopiDummy_in_place", "RTMPose_Test_Anim_in_place", "RTMPose_Test_Anim", "OctopiDummy")


def _log(message):
    unreal.log(f"[OctopiKnightSync] {message}")


def _warn(message):
    unreal.log_warning(f"[OctopiKnightSync] {message}")


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


def _skeletal_components(actor):
    comps = []
    primary = _skeletal_component(actor)
    if primary:
        comps.append(primary)
    try:
        for comp in actor.get_components_by_class(unreal.SkeletalMeshComponent):
            if comp and comp not in comps:
                comps.append(comp)
    except Exception:
        pass
    return comps


def _enable_editor_anim_update(comp):
    for prop, value in (
        ("update_animation_in_editor", True),
        ("enable_update_rate_optimizations", False),
        ("component_use_fixed_skel_bounds", False),
    ):
        try:
            comp.set_editor_property(prop, value)
        except Exception:
            pass

    option = getattr(unreal, "VisibilityBasedAnimTickOption", None)
    if option:
        for enum_name in ("ALWAYS_TICK_POSE_AND_REFRESH_BONES", "ALWAYS_TICK_POSE"):
            enum_value = getattr(option, enum_name, None)
            if enum_value is None:
                continue
            try:
                comp.set_editor_property("visibility_based_anim_tick_option", enum_value)
                break
            except Exception:
                pass


def cleanup_octopi_joint_markers():
    destroyed = 0
    for actor in list(unreal.EditorLevelLibrary.get_all_level_actors()):
        try:
            label = actor.get_actor_label()
        except Exception:
            continue
        if label.startswith("OctopiJoint_"):
            unreal.EditorLevelLibrary.destroy_actor(actor)
            destroyed += 1
    _log(f"Destroyed {destroyed} OctopiJoint marker actors.")
    return destroyed


def _selected_level_actors():
    selected = []
    try:
        selected = list(unreal.EditorLevelLibrary.get_selected_level_actors())
    except Exception:
        pass
    if selected:
        return selected
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        return list(subsystem.get_selected_level_actors())
    except Exception:
        return []


def find_knight_actor(name_hint=None):
    if str(name_hint).lower() == "selected":
        selected = [actor for actor in _selected_level_actors() if _skeletal_component(actor)]
        if not selected:
            raise RuntimeError("No selected skeletal actor found. Select the Knight actor in the level, then run again.")
        _log(f"Using selected skeletal actor: {selected[0].get_actor_label()}")
        return selected[0]

    hints = (name_hint,) if name_hint else KNIGHT_HINTS
    hints = tuple(str(h).lower() for h in hints if h)
    candidates = []

    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
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
        if "knight" in haystack:
            score += 50
        if score > 0:
            candidates.append((score, label, actor, mesh_name))

    if not candidates:
        labels = [a.get_actor_label() for a in unreal.EditorLevelLibrary.get_all_level_actors() if _skeletal_component(a)]
        raise RuntimeError(f"Could not find a Knight skeletal actor. Skeletal actors found: {labels}")

    candidates.sort(key=lambda item: (-item[0], item[1]))
    _log("Knight actor candidates:")
    for score, label, _actor, mesh_name in candidates[:10]:
        _log(f"  score={score:03d} actor={label} mesh={mesh_name}")
    return candidates[0][2]


def find_dummy_actor(name_hint=None):
    hints = (name_hint,) if name_hint else DUMMY_HINTS
    hints = tuple(str(h).lower() for h in hints if h)
    candidates = []

    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
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
        labels = [a.get_actor_label() for a in unreal.EditorLevelLibrary.get_all_level_actors() if _skeletal_component(a)]
        raise RuntimeError(
            "Could not find an imported Octopi dummy skeletal actor. "
            f"Skeletal actors found: {labels}"
        )

    candidates.sort(key=lambda item: (-item[0], item[1]))
    _log("Dummy actor candidates:")
    for score, label, _actor, mesh_name in candidates[:10]:
        _log(f"  score={score:03d} actor={label} mesh={mesh_name}")
    return candidates[0][2]


def _is_skeletal_mesh_asset(asset):
    if not asset:
        return False
    skeletal_mesh_class = getattr(unreal, "SkeletalMesh", None)
    if skeletal_mesh_class is not None and isinstance(asset, skeletal_mesh_class):
        return True
    try:
        return asset.get_class().get_name() == "SkeletalMesh"
    except Exception:
        return False


def find_dummy_mesh_asset():
    candidates = []
    for path in unreal.EditorAssetLibrary.list_assets("/Game", recursive=True, include_folder=False):
        lowered = path.lower()
        if not any(h.lower() in lowered for h in DUMMY_HINTS):
            continue
        asset = unreal.load_asset(path)
        if not _is_skeletal_mesh_asset(asset):
            continue
        score = 0
        for hint in DUMMY_HINTS:
            if hint.lower() in lowered:
                score += 100
        candidates.append((score, path, asset))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0], item[1]))
    _log("Dummy mesh asset candidates:")
    for score, path, _asset in candidates[:10]:
        _log(f"  score={score:03d} {path}")
    return candidates[0][2]


def find_dummy_animation_asset():
    candidates = []
    for path in unreal.EditorAssetLibrary.list_assets("/Game", recursive=True, include_folder=False):
        lowered = path.lower()
        if not any(h.lower() in lowered for h in DUMMY_ANIM_HINTS):
            continue
        asset = unreal.load_asset(path)
        if not _is_animation_asset(asset):
            continue
        score = 0
        for hint in DUMMY_ANIM_HINTS:
            if hint.lower() in lowered:
                score += 100
        candidates.append((score, path, asset))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0], item[1]))
    _log("Dummy animation asset candidates:")
    for score, path, _asset in candidates[:10]:
        _log(f"  score={score:03d} {path}")
    return candidates[0][2]


def spawn_dummy_actor_near(reference_actor):
    mesh = find_dummy_mesh_asset()
    if not mesh:
        raise RuntimeError(
            "No Octopi dummy actor is in the level, and I could not find an imported OctopiDummy skeletal mesh asset under /Game. "
            "Import C:/OCTOPI_Pipeline/outputs/gold_mocap_full_217f_mesh_dummy_fbx/OctopiDummy_in_place.fbx, then run again."
        )

    location = unreal.Vector(0.0, 0.0, 0.0)
    rotation = unreal.Rotator(0.0, 0.0, 0.0)
    try:
        location = reference_actor.get_actor_location() + unreal.Vector(150.0, 0.0, 0.0)
        rotation = reference_actor.get_actor_rotation()
    except Exception:
        pass

    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.SkeletalMeshActor, location, rotation)
    actor.set_actor_label("OctopiDummy_Compare")
    comp = _skeletal_component(actor)
    if not comp:
        raise RuntimeError("Spawned Octopi dummy actor, but it has no SkeletalMeshComponent.")

    for method_name in ("set_skeletal_mesh_asset", "set_skeletal_mesh"):
        method = getattr(comp, method_name, None)
        if not method:
            continue
        try:
            method(mesh)
            _log(f"Spawned OctopiDummy_Compare using mesh {mesh.get_path_name()}")
            break
        except Exception:
            pass
    else:
        try:
            comp.set_editor_property("skeletal_mesh", mesh)
            _log(f"Spawned OctopiDummy_Compare using mesh {mesh.get_path_name()}")
        except Exception as exc:
            raise RuntimeError(f"Could not assign dummy mesh to spawned actor: {exc}")

    anim = find_dummy_animation_asset()
    if anim:
        reset_and_play_animation(actor, anim, play_rate=1.0)
    else:
        _warn("Spawned dummy mesh, but could not find its animation asset. The dummy may stay in bind pose.")
    return actor


def _is_animation_asset(asset):
    if not asset:
        return False
    class_name = asset.get_class().get_name().lower()
    return "animsequence" in class_name or class_name == "animationasset"


def find_octopi_knight_animation(asset_path=None):
    if asset_path:
        asset = unreal.load_asset(asset_path)
        if not asset:
            raise RuntimeError(f"Could not load animation asset: {asset_path}")
        return asset

    candidates = []
    for path in unreal.EditorAssetLibrary.list_assets("/Game", recursive=True, include_folder=False):
        lowered = path.lower()
        if not any(h.lower() in lowered for h in ANIM_HINTS):
            continue
        asset = unreal.load_asset(path)
        if not _is_animation_asset(asset):
            continue
        score = 0
        for hint in ANIM_HINTS:
            if hint.lower() in lowered:
                score += 100
        if "knight" in lowered:
            score += 50
        candidates.append((score, path, asset))

    if not candidates:
        raise RuntimeError(
            "Could not find imported Octopi Knight animation under /Game. "
            "Import C:/OCTOPI_Pipeline/outputs/gold_mocap_full_217f_mesh_dummy_fbx/OctopiDummy_SK_Knight4_anim.fbx "
            "as animation for SK_Knight4, then run this again. If the asset has a different name, pass anim_asset_path."
        )

    candidates.sort(key=lambda item: (-item[0], item[1]))
    _log("Animation candidates:")
    for score, path, _asset in candidates[:10]:
        _log(f"  score={score:03d} {path}")
    return candidates[0][2]


def print_octopi_knight_debug():
    _log("Selected skeletal actors:")
    for actor in _selected_level_actors():
        for comp in _skeletal_components(actor):
            mesh_name = ""
            anim_name = ""
            mode = ""
            comp_name = ""
            try:
                comp_name = comp.get_name()
            except Exception:
                pass
            try:
                mesh = comp.get_editor_property("skeletal_mesh")
                mesh_name = mesh.get_path_name() if mesh else ""
            except Exception:
                pass
            for prop in ("animation_mode", "animation_data"):
                try:
                    value = comp.get_editor_property(prop)
                    if prop == "animation_mode":
                        mode = str(value)
                    elif value:
                        anim_name = str(value)
                except Exception:
                    pass
            _log(f"  actor={actor.get_actor_label()} comp={comp_name} mesh={mesh_name} mode={mode} animation_data={anim_name}")

    _log("Octopi/Knight animation assets under /Game:")
    found = 0
    for path in unreal.EditorAssetLibrary.list_assets("/Game", recursive=True, include_folder=False):
        lowered = path.lower()
        if not any(h.lower() in lowered for h in ANIM_HINTS):
            continue
        asset = unreal.load_asset(path)
        class_name = asset.get_class().get_name() if asset else "<missing>"
        _log(f"  {path} class={class_name}")
        found += 1
    if not found:
        _warn("No matching Octopi/Knight animation assets found. Import OctopiDummy_SK_Knight4_anim.fbx as animation for SK_Knight4.")


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


def reset_and_play_current_animation(actor, play_rate=1.0):
    comp = _skeletal_component(actor)
    if not comp:
        raise RuntimeError(f"Actor has no SkeletalMeshComponent: {actor.get_actor_label()}")

    _enable_editor_anim_update(comp)

    _set_play_rate(comp, play_rate, actor.get_actor_label())
    for method_name, args in (("set_position", (0.0, False)), ("set_playing", (True,)), ("play", (True,))):
        method = getattr(comp, method_name, None)
        if not method:
            continue
        try:
            method(*args)
            _log(f"{actor.get_actor_label()}.{method_name}{args}")
        except Exception as exc:
            _warn(f"{method_name}{args} failed on {actor.get_actor_label()}: {exc}")

    try:
        comp.tick_animation(0.0, False)
        comp.refresh_bone_transforms()
    except Exception:
        pass
    return comp


def reset_and_play_animation(actor, animation_asset, play_rate=1.0):
    comp = _skeletal_component(actor)
    if not comp:
        raise RuntimeError(f"Actor has no SkeletalMeshComponent: {actor.get_actor_label()}")

    try:
        comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    except Exception:
        pass
    _enable_editor_anim_update(comp)

    played_directly = False
    method = getattr(comp, "play_animation", None)
    if method:
        try:
            method(animation_asset, True)
            played_directly = True
            _log(f"{actor.get_actor_label()}.play_animation({animation_asset.get_name()}, True)")
        except Exception as exc:
            _warn(f"play_animation failed on {actor.get_actor_label()}: {exc}")

    for method_name in ("set_animation", "set_animation_asset"):
        method = getattr(comp, method_name, None)
        if not method:
            continue
        try:
            method(animation_asset)
            _log(f"{actor.get_actor_label()}.{method_name}({animation_asset.get_name()})")
            break
        except Exception as exc:
            _warn(f"{method_name} failed on {actor.get_actor_label()}: {exc}")

    for prop, value in (
        ("animation_mode", unreal.AnimationMode.ANIMATION_SINGLE_NODE),
        ("animation_data", animation_asset),
    ):
        try:
            comp.set_editor_property(prop, value)
            _log(f"{actor.get_actor_label()}.set_editor_property({prop}, {value})")
        except Exception:
            pass

    _set_play_rate(comp, play_rate, actor.get_actor_label())
    for method_name, args in (("set_position", (0.0, False)), ("set_playing", (True,)), ("play", (True,))):
        method = getattr(comp, method_name, None)
        if not method:
            continue
        try:
            method(*args)
            _log(f"{actor.get_actor_label()}.{method_name}{args}")
        except Exception as exc:
            _warn(f"{method_name}{args} failed on {actor.get_actor_label()}: {exc}")

    if not played_directly:
        method = getattr(comp, "play_animation", None)
        if method:
            try:
                method(animation_asset, True)
                _log(f"{actor.get_actor_label()}.play_animation({animation_asset.get_name()}, True)")
            except Exception:
                pass

    try:
        comp.tick_animation(0.0, False)
        comp.refresh_bone_transforms()
    except Exception:
        pass
    return comp


def _manual_anim_position(comp, seconds, fire_notifies=False):
    for method_name, args in (
        ("set_position", (float(seconds), bool(fire_notifies))),
        ("set_position_with_previous_time", (float(seconds), 0.0, bool(fire_notifies))),
    ):
        method = getattr(comp, method_name, None)
        if not method:
            continue
        try:
            method(*args)
            return True
        except Exception:
            pass

    try:
        inst = comp.get_anim_instance()
        if inst:
            for method_name, args in (
                ("set_position", (float(seconds), bool(fire_notifies))),
                ("set_position_with_previous_time", (float(seconds), 0.0, bool(fire_notifies))),
            ):
                method = getattr(inst, method_name, None)
                if method:
                    method(*args)
                    return True
    except Exception:
        pass
    return False


def _refresh_anim_component(comp):
    try:
        comp.tick_animation(0.0, False)
    except Exception:
        pass
    try:
        comp.refresh_bone_transforms()
    except Exception:
        pass
    try:
        comp.mark_render_transform_dirty()
    except Exception:
        pass


def _start_manual_actor_anim_clock(actors, fps=60.0, loop=True):
    old_state = getattr(unreal, "_octopi_manual_anim_clock_state", None)
    if old_state and old_state.get("tick_handle") is not None:
        try:
            unreal.unregister_slate_post_tick_callback(old_state["tick_handle"])
        except Exception:
            pass

    comps = []
    for actor in actors:
        for comp in _skeletal_components(actor):
            _enable_editor_anim_update(comp)
            comps.append(comp)

    state = {
        "time": 0.0,
        "fps": float(fps),
        "loop": bool(loop),
        "paused": False,
        "comps": comps,
        "tick_handle": None,
    }

    def tick(delta_seconds):
        if state.get("paused"):
            return
        state["time"] += float(delta_seconds)
        # Demo source is 217 frames at 60fps, so wrap near 3.62s if the asset
        # length is not exposed through this UE Python build.
        max_time = 217.0 / max(state["fps"], 1e-6)
        if state["loop"] and state["time"] > max_time:
            state["time"] = 0.0
        for comp in state["comps"]:
            _manual_anim_position(comp, state["time"], False)
            _refresh_anim_component(comp)

    handle = unreal.register_slate_post_tick_callback(tick)
    state["tick_handle"] = handle
    setattr(unreal, "_octopi_manual_anim_clock_state", state)
    _log(f"Started manual editor animation clock for {len(comps)} skeletal components.")


def _set_manual_actor_anim_clock_paused(paused):
    state = getattr(unreal, "_octopi_manual_anim_clock_state", None)
    if state:
        state["paused"] = bool(paused)


def _stop_manual_actor_anim_clock():
    state = getattr(unreal, "_octopi_manual_anim_clock_state", None)
    if state and state.get("tick_handle") is not None:
        try:
            unreal.unregister_slate_post_tick_callback(state["tick_handle"])
        except Exception:
            pass
    setattr(unreal, "_octopi_manual_anim_clock_state", None)


def _set_skeletal_playing(actor, playing):
    comp = _skeletal_component(actor)
    if not comp:
        return False
    changed = False
    for method_name, args in (("set_playing", (bool(playing),)), ("play", (True,)) if playing else ("stop", ())):
        method = getattr(comp, method_name, None)
        if not method:
            continue
        try:
            method(*args)
            changed = True
        except Exception as exc:
            _warn(f"{actor.get_actor_label()}.{method_name}{args} failed: {exc}")
    return changed


def _load_joint_player_functions():
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


def run_octopi_knight_compare(name_hint=None, anim_asset_path=None, fps=60.0, loop=True, clean_markers=True, use_current_animation=False):
    if clean_markers:
        cleanup_octopi_joint_markers()

    actor = find_knight_actor(name_hint)
    _log(f"Using Knight actor: {actor.get_actor_label()}")

    fps = float(fps)
    dummy_play_rate = fps / DUMMY_SOURCE_FPS
    if use_current_animation:
        _log("Keeping the Knight's currently assigned animation asset.")
        reset_and_play_current_animation(actor, play_rate=dummy_play_rate)
    else:
        anim = find_octopi_knight_animation(anim_asset_path)
        _log(f"Using animation: {anim.get_path_name()}")
        reset_and_play_animation(actor, anim, play_rate=dummy_play_rate)

    funcs = _load_joint_player_functions()
    setattr(unreal, "_octopi_joint_player_functions", funcs)
    funcs["start_octopi_json_playback"](
        input_path=JSON_INPUT,
        fps=fps,
        loop=bool(loop),
        space="root_motion",
        scale=10.0,
    )
    reset_func = funcs.get("reset_octopi_json_playback_to_zero")
    if reset_func:
        reset_func()

    setattr(unreal, "_octopi_knight_compare_state", {"actor": actor, "fps": fps, "paused": False})
    _log(f"Knight compare started. fps={fps:g} play_rate={dummy_play_rate:g} loop={loop}")
    return actor


def run_octopi_original_vs_dummy_compare(
    knight_hint="selected",
    dummy_hint=None,
    fps=60.0,
    loop=True,
    show_joint_overlay=True,
    clean_markers=True,
):
    """Play the original Knight animation and imported Octopi dummy together.

    The Knight keeps whatever animation is currently assigned in its Details
    panel, such as One_Hand_Club_Combo_Anim2. The dummy also keeps its current
    imported animation asset. Both are reset to frame zero and played together.
    """
    if clean_markers:
        cleanup_octopi_joint_markers()

    knight = find_knight_actor(knight_hint)
    try:
        dummy = find_dummy_actor(dummy_hint)
    except RuntimeError as exc:
        _warn(str(exc))
        dummy = spawn_dummy_actor_near(knight)
    fps = float(fps)
    play_rate = fps / DUMMY_SOURCE_FPS

    _log(f"Using original Knight actor: {knight.get_actor_label()}")
    _log(f"Using Octopi dummy actor: {dummy.get_actor_label()}")
    _log("Keeping both actors' currently assigned animation assets.")

    reset_and_play_current_animation(knight, play_rate=play_rate)
    reset_and_play_current_animation(dummy, play_rate=play_rate)
    _start_manual_actor_anim_clock((knight, dummy), fps=fps, loop=loop)

    if show_joint_overlay:
        funcs = _load_joint_player_functions()
        setattr(unreal, "_octopi_joint_player_functions", funcs)
        funcs["start_octopi_json_playback"](
            input_path=JSON_INPUT,
            fps=fps,
            loop=bool(loop),
            space="root_motion",
            scale=10.0,
        )
        reset_func = funcs.get("reset_octopi_json_playback_to_zero")
        if reset_func:
            reset_func()
    else:
        stop_json = _joint_player_function("stop_existing_player")
        if stop_json:
            stop_json()

    setattr(
        unreal,
        "_octopi_knight_compare_state",
        {
            "actor": knight,
            "dummy": dummy,
            "fps": fps,
            "paused": False,
            "mode": "original_vs_dummy",
        },
    )
    _log(f"Original-vs-dummy compare started. fps={fps:g} play_rate={play_rate:g} loop={loop}")
    return knight, dummy


def pause_octopi_knight_compare():
    state = getattr(unreal, "_octopi_knight_compare_state", None)
    actor = state.get("actor") if state else None
    dummy = state.get("dummy") if state else None
    if actor:
        _set_skeletal_playing(actor, False)
    if dummy:
        _set_skeletal_playing(dummy, False)
    pause_json = _joint_player_function("pause_octopi_json_playback")
    if pause_json:
        pause_json()
    if state:
        state["paused"] = True
    _set_manual_actor_anim_clock_paused(True)
    _log("Paused Knight compare.")


def play_octopi_knight_compare():
    state = getattr(unreal, "_octopi_knight_compare_state", None)
    actor = state.get("actor") if state else None
    dummy = state.get("dummy") if state else None
    if actor:
        _set_skeletal_playing(actor, True)
    if dummy:
        _set_skeletal_playing(dummy, True)
    resume_json = _joint_player_function("resume_octopi_json_playback")
    if resume_json:
        resume_json()
    if state:
        state["paused"] = False
    _set_manual_actor_anim_clock_paused(False)
    _log("Playing Knight compare.")


def toggle_octopi_knight_compare():
    state = getattr(unreal, "_octopi_knight_compare_state", None)
    if state and state.get("paused", False):
        play_octopi_knight_compare()
    else:
        pause_octopi_knight_compare()


def stop_octopi_knight_compare():
    state = getattr(unreal, "_octopi_knight_compare_state", None)
    actor = state.get("actor") if state else None
    dummy = state.get("dummy") if state else None
    if actor:
        _set_skeletal_playing(actor, False)
    if dummy:
        _set_skeletal_playing(dummy, False)
    _stop_manual_actor_anim_clock()
    stop_json = _joint_player_function("stop_existing_player")
    if stop_json:
        stop_json()
    setattr(unreal, "_octopi_knight_compare_state", None)
    _log("Stopped Knight compare.")


builtins.run_octopi_knight_compare = run_octopi_knight_compare
builtins.run_octopi_original_vs_dummy_compare = run_octopi_original_vs_dummy_compare
builtins.pause_octopi_knight_compare = pause_octopi_knight_compare
builtins.play_octopi_knight_compare = play_octopi_knight_compare
builtins.toggle_octopi_knight_compare = toggle_octopi_knight_compare
builtins.stop_octopi_knight_compare = stop_octopi_knight_compare
builtins.cleanup_octopi_joint_markers = cleanup_octopi_joint_markers
builtins.print_octopi_knight_debug = print_octopi_knight_debug
globals()["run_octopi_knight_compare"] = run_octopi_knight_compare
globals()["run_octopi_original_vs_dummy_compare"] = run_octopi_original_vs_dummy_compare
globals()["pause_octopi_knight_compare"] = pause_octopi_knight_compare
globals()["play_octopi_knight_compare"] = play_octopi_knight_compare
globals()["toggle_octopi_knight_compare"] = toggle_octopi_knight_compare
globals()["stop_octopi_knight_compare"] = stop_octopi_knight_compare
globals()["cleanup_octopi_joint_markers"] = cleanup_octopi_joint_markers
globals()["print_octopi_knight_debug"] = print_octopi_knight_debug
_log("Loaded. Run: run_octopi_original_vs_dummy_compare(knight_hint='selected'), then play/pause/toggle/stop_octopi_knight_compare()")
