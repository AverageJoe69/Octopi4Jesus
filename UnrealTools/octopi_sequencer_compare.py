"""
Add the Octopi dummy animation to the currently open Sequencer.

Use this when the original Knight animation already plays correctly from
Sequencer and you want the Octopi dummy to play alongside it.

Run inside Unreal Editor Python while the target Level Sequence is open:

    exec(open(r"C:/OCTOPI_Pipeline/UnrealTools/octopi_sequencer_compare.py").read())
    add_octopi_dummy_to_open_sequence(knight_hint="selected")

Then press Play in Sequencer's transport controls, not the main editor PIE Play
button.
"""

from __future__ import annotations

import builtins

import unreal


DUMMY_HINTS = ("OctopiDummy_in_place", "OctopiDummy", "rtmpose", "dummy")
DUMMY_ANIM_HINTS = ("OctopiDummy_in_place", "RTMPose_Test_Anim_in_place", "RTMPose_Test_Anim", "OctopiDummy")
FRAME_COUNT = 217
FPS = 60


def _log(message):
    unreal.log(f"[OctopiSequencer] {message}")


def _warn(message):
    unreal.log_warning(f"[OctopiSequencer] {message}")


def _all_level_actors():
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        return list(subsystem.get_all_level_actors())
    except Exception:
        return list(unreal.EditorLevelLibrary.get_all_level_actors())


def _selected_level_actors():
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        return list(subsystem.get_selected_level_actors())
    except Exception:
        return list(unreal.EditorLevelLibrary.get_selected_level_actors())


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


def _is_animation_asset(asset):
    if not asset:
        return False
    try:
        class_name = asset.get_class().get_name().lower()
    except Exception:
        return False
    return "animsequence" in class_name or class_name == "animationasset"


def _score_path(path, hints):
    lowered = path.lower()
    score = 0
    for hint in hints:
        if hint.lower() in lowered:
            score += 100
    return score


def find_asset_by_hints(hints, predicate, label):
    candidates = []
    for path in unreal.EditorAssetLibrary.list_assets("/Game", recursive=True, include_folder=False):
        score = _score_path(path, hints)
        if score <= 0:
            continue
        asset = unreal.load_asset(path)
        if predicate(asset):
            candidates.append((score, path, asset))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0], item[1]))
    _log(f"{label} candidates:")
    for score, path, _asset in candidates[:10]:
        _log(f"  score={score:03d} {path}")
    return candidates[0][2]


def find_dummy_actor():
    candidates = []
    for actor in _all_level_actors():
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
        for hint in DUMMY_HINTS:
            if hint.lower() in haystack:
                score += 100
        if score > 0:
            candidates.append((score, label, actor, mesh_name))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0], item[1]))
    _log("Dummy actor candidates:")
    for score, label, _actor, mesh_name in candidates[:10]:
        _log(f"  score={score:03d} actor={label} mesh={mesh_name}")
    return candidates[0][2]


def selected_reference_actor():
    for actor in _selected_level_actors():
        if _skeletal_component(actor):
            return actor
    return None


def spawn_dummy_near(reference_actor=None):
    mesh = find_asset_by_hints(DUMMY_HINTS, _is_skeletal_mesh_asset, "Dummy mesh asset")
    if not mesh:
        raise RuntimeError(
            "Could not find an imported OctopiDummy skeletal mesh under /Game. "
            "Import C:/OCTOPI_Pipeline/outputs/gold_mocap_full_217f_mesh_dummy_fbx/OctopiDummy_in_place.fbx first."
        )

    location = unreal.Vector(0.0, 0.0, 0.0)
    rotation = unreal.Rotator(0.0, 0.0, 0.0)
    if reference_actor:
        try:
            location = reference_actor.get_actor_location() + unreal.Vector(120.0, 0.0, 0.0)
            rotation = reference_actor.get_actor_rotation()
        except Exception:
            pass

    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.SkeletalMeshActor, location, rotation)
    actor.set_actor_label("OctopiDummy_SequencerCompare")
    comp = _skeletal_component(actor)
    if not comp:
        raise RuntimeError("Spawned Octopi dummy actor without a SkeletalMeshComponent.")

    for method_name in ("set_skeletal_mesh_asset", "set_skeletal_mesh"):
        method = getattr(comp, method_name, None)
        if not method:
            continue
        try:
            method(mesh)
            _log(f"Spawned {actor.get_actor_label()} using {mesh.get_path_name()}")
            return actor
        except Exception:
            pass

    comp.set_editor_property("skeletal_mesh", mesh)
    _log(f"Spawned {actor.get_actor_label()} using {mesh.get_path_name()}")
    return actor


def current_level_sequence():
    lib = getattr(unreal, "LevelSequenceEditorBlueprintLibrary", None)
    if not lib:
        raise RuntimeError("LevelSequenceEditorBlueprintLibrary is unavailable. Open Sequencer and try again.")
    sequence = lib.get_current_level_sequence()
    if not sequence:
        raise RuntimeError("No current Level Sequence. Open the sequence that plays the Knight, then run again.")
    return sequence


def _set_sequence_range(sequence):
    try:
        sequence.set_display_rate(unreal.FrameRate(FPS, 1))
    except Exception:
        pass
    for method_name, args in (
        ("set_playback_start", (0,)),
        ("set_playback_end", (FRAME_COUNT,)),
        ("set_work_range_start", (0.0,)),
        ("set_work_range_end", (FRAME_COUNT / FPS,)),
    ):
        method = getattr(sequence, method_name, None)
        if method:
            try:
                method(*args)
            except Exception:
                pass


def _binding_for_actor(sequence, actor):
    actor_name = actor.get_actor_label()
    try:
        for binding in sequence.get_bindings():
            for bound in unreal.LevelSequenceEditorBlueprintLibrary.get_bound_objects(binding):
                if bound == actor:
                    return binding
            if binding.get_name() == actor_name:
                return binding
    except Exception:
        pass
    binding = sequence.add_possessable(actor)
    _log(f"Added Sequencer possessable binding for {actor_name}")
    return binding


def _clear_skeletal_animation_tracks(binding):
    for track in list(binding.get_tracks()):
        try:
            if track.get_class().get_name() == "MovieSceneSkeletalAnimationTrack":
                binding.remove_track(track)
        except Exception:
            pass


def _add_animation_track(binding, animation_asset):
    track = binding.add_track(unreal.MovieSceneSkeletalAnimationTrack)
    section = track.add_section()
    section.set_range(0, FRAME_COUNT)

    params = unreal.MovieSceneSkeletalAnimationParams()
    for prop in ("animation", "animation_asset"):
        try:
            params.set_editor_property(prop, animation_asset)
            break
        except Exception:
            pass
    section.set_editor_property("params", params)
    _log(f"Added animation section: {animation_asset.get_path_name()}")
    return section


def add_octopi_dummy_to_open_sequence(knight_hint="selected", replace_existing_tracks=True):
    sequence = current_level_sequence()
    reference = selected_reference_actor() if knight_hint == "selected" else None
    dummy = find_dummy_actor()
    if not dummy:
        dummy = spawn_dummy_near(reference)

    anim = find_asset_by_hints(DUMMY_ANIM_HINTS, _is_animation_asset, "Dummy animation asset")
    if not anim:
        raise RuntimeError(
            "Could not find the imported Octopi dummy animation asset under /Game. "
            "Reimport OctopiDummy_in_place.fbx with animation enabled."
        )

    binding = _binding_for_actor(sequence, dummy)
    if replace_existing_tracks:
        _clear_skeletal_animation_tracks(binding)
    _add_animation_track(binding, anim)
    _set_sequence_range(sequence)

    try:
        unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
    except Exception:
        pass
    _log("Ready. Press Play in Sequencer's transport controls, not the main editor PIE Play button.")
    return dummy


builtins.add_octopi_dummy_to_open_sequence = add_octopi_dummy_to_open_sequence
globals()["add_octopi_dummy_to_open_sequence"] = add_octopi_dummy_to_open_sequence
_log("Loaded. Run: add_octopi_dummy_to_open_sequence(knight_hint='selected')")
