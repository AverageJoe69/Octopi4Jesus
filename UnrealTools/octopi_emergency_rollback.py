"""
Emergency cleanup for Octopi demo helpers.

Run inside Unreal Python:

    exec(open(r"C:/OCTOPI_Pipeline/UnrealTools/octopi_emergency_rollback.py").read())

This removes only transient compare actors/bindings/callbacks created by the
Octopi helper scripts. It does not delete imported assets or the Knight actor.
"""

from __future__ import annotations

import unreal


LABEL_PREFIXES = (
    "OctopiJoint_",
    "OctopiDummy_Compare",
    "OctopiDummy_SequencerCompare",
)


def log(message):
    unreal.log(f"[OctopiRollback] {message}")


def warn(message):
    unreal.log_warning(f"[OctopiRollback] {message}")


def all_level_actors():
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        return list(subsystem.get_all_level_actors())
    except Exception:
        return list(unreal.EditorLevelLibrary.get_all_level_actors())


def destroy_actor(actor):
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        return subsystem.destroy_actor(actor)
    except Exception:
        return unreal.EditorLevelLibrary.destroy_actor(actor)


def stop_callbacks():
    for attr in ("_octopi_joint_player_state", "_octopi_manual_anim_clock_state"):
        state = getattr(unreal, attr, None)
        handle = state.get("tick_handle") if isinstance(state, dict) else None
        if handle is not None:
            try:
                unreal.unregister_slate_post_tick_callback(handle)
                log(f"Stopped callback from {attr}.")
            except Exception as exc:
                warn(f"Could not stop callback from {attr}: {exc}")
        setattr(unreal, attr, None)

    for attr in ("_octopi_knight_compare_state", "_octopi_synced_compare_state", "_octopi_joint_player_functions"):
        try:
            setattr(unreal, attr, None)
        except Exception:
            pass


def binding_name(binding):
    for method_name in ("get_name", "get_display_name"):
        method = getattr(binding, method_name, None)
        if method:
            try:
                return str(method())
            except Exception:
                pass
    return ""


def remove_octopi_sequence_bindings():
    lib = getattr(unreal, "LevelSequenceEditorBlueprintLibrary", None)
    if not lib:
        return 0
    try:
        sequence = lib.get_current_level_sequence()
    except Exception:
        sequence = None
    if not sequence:
        return 0

    removed = 0
    bindings = list(sequence.get_bindings())
    for binding in bindings:
        name = binding_name(binding)
        lowered = name.lower()
        if "octopidummy" not in lowered and "octopijoint" not in lowered:
            continue

        ok = False
        for method_name in ("remove_binding", "remove_possessable", "remove_spawnable"):
            method = getattr(sequence, method_name, None)
            if not method:
                continue
            for arg in (binding, getattr(binding, "get_id", lambda: None)()):
                if arg is None:
                    continue
                try:
                    method(arg)
                    ok = True
                    break
                except Exception:
                    pass
            if ok:
                break

        if not ok:
            try:
                for track in list(binding.get_tracks()):
                    binding.remove_track(track)
                ok = True
            except Exception:
                pass

        if ok:
            removed += 1
            log(f"Removed/cleared sequence binding: {name}")
        else:
            warn(f"Could not remove sequence binding automatically: {name}")

    try:
        lib.refresh_current_level_sequence()
    except Exception:
        pass
    return removed


def destroy_transient_octopi_actors():
    destroyed = 0
    for actor in list(all_level_actors()):
        try:
            label = actor.get_actor_label()
        except Exception:
            continue
        if any(label.startswith(prefix) for prefix in LABEL_PREFIXES):
            destroy_actor(actor)
            destroyed += 1
            log(f"Destroyed actor: {label}")
    return destroyed


def main():
    stop_callbacks()
    removed = remove_octopi_sequence_bindings()
    destroyed = destroy_transient_octopi_actors()
    log(f"Rollback complete. Removed/cleared sequence bindings: {removed}. Destroyed actors: {destroyed}.")
    log("If the Level Sequence is still dirty, do not save it unless the outliner looks correct.")


main()
