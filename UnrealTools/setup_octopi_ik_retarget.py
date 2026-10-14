"""
Create clean IK Rig chains and an IK Retargeter for the Octopi RTMPose dummy.

Run inside Unreal Editor Python, for example:

    py C:/OCTOPI_Pipeline/UnrealTools/setup_octopi_ik_retarget.py

Edit the CONFIG block below for your actual imported asset paths.

This script does not rename or modify imported FBX animation assets. It creates
or updates IK Rig / IK Retargeter assets and replaces their retarget chains.
"""

from __future__ import annotations

import sys
import unreal


# ---------------------------------------------------------------------------
# CONFIG - edit these paths to match your Unreal project.
# ---------------------------------------------------------------------------

SOURCE_SKELETAL_MESH = "/Game/_GENERATED/joeconway/OctopiDummy_in_place"
TARGET_SKELETAL_MESH = "/Game/Characters/Knight4/SK_Knight4"

SOURCE_IK_RIG = "/Game/Octopi/RTMPose/IKR_RTMPoseDummy_Clean"
TARGET_IK_RIG = "/Game/Octopi/RTMPose/IKR_Knight4_Clean"
IK_RETARGETER = "/Game/Octopi/RTMPose/RTG_RTMPose_To_Knight4_Clean"


SOURCE_CHAINS = {
    "Spine": ("pelvis", "neck"),
    "Head": ("neck", "head"),
    "LeftArm": ("left_upper_arm", "left_hand"),
    "RightArm": ("right_upper_arm", "right_hand"),
    "LeftLeg": ("left_thigh", "left_foot"),
    "RightLeg": ("right_thigh", "right_foot"),
}

SOURCE_CHAIN_CANDIDATES = {
    "Spine": (("pelvis", "neck"), ("pelvis", "spine")),
    "Head": (("neck", "head"), ("neck", "nose")),
    "LeftArm": (("left_upper_arm", "left_hand"), ("upperarm_l", "hand_l"), ("left_upper_arm", "left_forearm"), ("left_shoulder", "left_wrist")),
    "RightArm": (("right_upper_arm", "right_hand"), ("upperarm_r", "hand_r"), ("right_upper_arm", "right_forearm"), ("right_shoulder", "right_wrist")),
    "LeftLeg": (("left_thigh", "left_foot"), ("thigh_l", "foot_l"), ("left_thigh", "left_calf"), ("left_hip", "left_ankle")),
    "RightLeg": (("right_thigh", "right_foot"), ("thigh_r", "foot_r"), ("right_thigh", "right_calf"), ("right_hip", "right_ankle")),
}

TARGET_CHAINS = {
    "Spine": ("pelvis", "spine_03"),
    "Head": ("neck_01", "head"),
    "LeftArm": ("upperarm_l", "hand_l"),
    "RightArm": ("upperarm_r", "hand_r"),
    "LeftLeg": ("thigh_l", "foot_l"),
    "RightLeg": ("thigh_r", "foot_r"),
}

CHAIN_MAP = {
    "Spine": "Spine",
    "Head": "Head",
    "LeftArm": "LeftArm",
    "RightArm": "RightArm",
    "LeftLeg": "LeftLeg",
    "RightLeg": "RightLeg",
}

CREATED_SOURCE_CHAINS: list[str] = []
CREATED_TARGET_CHAINS: list[str] = []
CREATED_CHAIN_MAPPINGS: list[str] = []


def log(message: str) -> None:
    unreal.log(f"[OctopiIK] {message}")


def warn(message: str) -> None:
    unreal.log_warning(f"[OctopiIK] {message}")


def error(message: str) -> None:
    unreal.log_error(f"[OctopiIK] {message}")


def split_asset_path(asset_path: str) -> tuple[str, str]:
    package_path, asset_name = asset_path.rsplit("/", 1)
    return package_path, asset_name


def load_required_asset(asset_path: str):
    asset = unreal.load_asset(asset_path)
    if not asset:
        raise RuntimeError(f"Could not load required asset: {asset_path}")
    return asset


def is_skeletal_mesh(asset) -> bool:
    skeletal_mesh_class = getattr(unreal, "SkeletalMesh", None)
    if skeletal_mesh_class is not None and isinstance(asset, skeletal_mesh_class):
        return True
    return asset is not None and asset.get_class().get_name() == "SkeletalMesh"


def get_skeleton_bone_names_from_mesh(skeletal_mesh) -> set[str]:
    names = set()
    for method_name in ("get_editor_property",):
        try:
            skeleton = skeletal_mesh.get_editor_property("skeleton")
            if skeleton:
                ref_skel = skeleton.get_editor_property("reference_skeleton")
                for idx in range(ref_skel.get_raw_bone_num()):
                    names.add(str(ref_skel.get_raw_ref_bone_name(idx)))
        except Exception:
            pass
    try:
        ref_skel = skeletal_mesh.get_editor_property("ref_skeleton")
        for idx in range(ref_skel.get_raw_bone_num()):
            names.add(str(ref_skel.get_raw_ref_bone_name(idx)))
    except Exception:
        pass
    return names


def choose_chains_for_mesh(skeletal_mesh, chains, candidates=None):
    bone_names = get_skeleton_bone_names_from_mesh(skeletal_mesh)
    if not bone_names:
        warn(f"Could not inspect bones for {skeletal_mesh.get_name()}; using configured chains.")
        return chains

    log(f"{skeletal_mesh.get_name()} bone count: {len(bone_names)}")
    chosen = {}
    for chain_name, default_pair in chains.items():
        options = candidates.get(chain_name, (default_pair,)) if candidates else (default_pair,)
        selected = None
        for start_bone, end_bone in options:
            if start_bone in bone_names and end_bone in bone_names:
                selected = (start_bone, end_bone)
                break
        if selected is None:
            warn(f"Skipping chain {chain_name}; no valid start/end pair found. Tried: {options}")
            continue
        chosen[chain_name] = selected
    return chosen


def find_knight4_skeletal_mesh():
    asset = unreal.load_asset(TARGET_SKELETAL_MESH)
    if asset and is_skeletal_mesh(asset):
        log(f"Loaded configured target skeletal mesh: {TARGET_SKELETAL_MESH}")
        return asset

    log(f"Configured target skeletal mesh path was not found: {TARGET_SKELETAL_MESH}")
    log("Searching /Game for Knight4 target skeletal mesh...")

    candidates = []
    for path in unreal.EditorAssetLibrary.list_assets("/Game", recursive=True, include_folder=False):
        lowered = path.lower()
        if "knight4" not in lowered and "knight" not in lowered:
            continue
        asset = unreal.load_asset(path)
        if not asset or not is_skeletal_mesh(asset):
            continue
        score = 0
        if "/game/knight4/mesh/sk_knight4.sk_knight4" == lowered:
            score += 1000
        if "sk_knight4.sk_knight4" in lowered:
            score += 500
        if "sk_knight4_basebody" in lowered:
            score += 300
        if "/mesh/" in lowered:
            score += 50
        if "separatedmeshes" in lowered or "hair_and_beards" in lowered:
            score -= 100
        candidates.append((score, path, asset))

    if not candidates:
        raise RuntimeError("Could not find a Knight4/Knight SkeletalMesh under /Game.")

    candidates.sort(key=lambda item: (-item[0], item[1]))
    log("Target skeletal mesh candidates:")
    for score, path, _asset in candidates[:20]:
        log(f"  score={score:04d} {path}")

    chosen = candidates[0]
    log(f"Auto-selected target skeletal mesh: {chosen[1]}")
    return chosen[2]


def save_asset(asset_path: str) -> None:
    unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False)
    log(f"Saved {asset_path}")


def save_loaded_asset(asset) -> None:
    method = getattr(unreal.EditorAssetLibrary, "save_loaded_asset", None)
    if method:
        method(asset, only_if_is_dirty=False)
        return
    unreal.EditorAssetLibrary.save_asset(asset.get_path_name(), only_if_is_dirty=False)


def find_class(*names):
    for name in names:
        value = getattr(unreal, name, None)
        if value is not None:
            return value
    return None


def create_asset_if_missing(asset_path: str, asset_class_name: str, factory_names: tuple[str, ...]):
    existing = unreal.load_asset(asset_path)
    if existing:
        log(f"Using existing asset: {asset_path}")
        return existing

    asset_class = find_class(asset_class_name)
    if asset_class is None:
        raise RuntimeError(f"Unreal Python class not found: unreal.{asset_class_name}")

    factory_class = find_class(*factory_names)
    if factory_class is None:
        raise RuntimeError(
            "No compatible factory found for "
            f"{asset_class_name}. Tried: {', '.join('unreal.' + n for n in factory_names)}"
        )

    package_path, asset_name = split_asset_path(asset_path)
    unreal.EditorAssetLibrary.make_directory(package_path)
    factory = factory_class()
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    asset = asset_tools.create_asset(asset_name, package_path, asset_class, factory)
    if not asset:
        raise RuntimeError(f"Failed to create asset: {asset_path}")

    log(f"Created asset: {asset_path}")
    return asset


def get_ik_rig_controller(ik_rig):
    controller_class = find_class("IKRigController")
    if controller_class is None:
        raise RuntimeError("unreal.IKRigController is not available. Enable the IK Rig plugin.")

    for method_name in ("get_controller", "get_ik_rig_controller"):
        method = getattr(controller_class, method_name, None)
        if method:
            return method(ik_rig)

    raise RuntimeError("Could not get IK Rig controller. Expected IKRigController.get_controller().")


def set_preview_mesh(controller, skeletal_mesh) -> None:
    for method_name in ("set_skeletal_mesh", "set_preview_mesh", "set_preview_skeletal_mesh"):
        method = getattr(controller, method_name, None)
        if method:
            method(skeletal_mesh)
            log(f"Set IK Rig preview mesh via {method_name}: {skeletal_mesh.get_name()}")
            return
    warn("Could not set preview skeletal mesh: controller has no known set-preview method.")


def remove_all_retarget_chains(controller) -> None:
    names = []

    for method_name in ("get_retarget_chains", "get_retarget_chain_names"):
        method = getattr(controller, method_name, None)
        if method:
            try:
                result = method()
                for item in result:
                    names.append(str(getattr(item, "chain_name", item)))
            except Exception as exc:
                warn(f"{method_name} failed while listing chains: {exc}")

    if not names:
        warn("No existing chains found via Python API. Continuing with chain creation.")

    for name in sorted(set(names)):
        for method_name in ("remove_retarget_chain", "remove_retarget_chain_by_name"):
            method = getattr(controller, method_name, None)
            if method:
                try:
                    method(name)
                    log(f"Deleted old chain: {name}")
                    break
                except Exception as exc:
                    warn(f"Could not delete chain {name} with {method_name}: {exc}")


def set_retarget_root(controller, root_bone: str) -> None:
    for method_name in ("set_retarget_root", "set_root_bone", "set_retarget_root_bone"):
        method = getattr(controller, method_name, None)
        if method:
            method(root_bone)
            log(f"Set retarget root: {root_bone}")
            return
    warn("Could not set retarget root: controller has no known root setter.")


def add_retarget_chain(controller, chain_name: str, start_bone: str, end_bone: str, created_log: list[str]) -> None:
    method = getattr(controller, "add_retarget_chain", None)
    if method:
        try:
            method(chain_name, start_bone, end_bone, "")
            log(f"Created chain {chain_name}: {start_bone} -> {end_bone}")
            created_log.append(f"{chain_name}: {start_bone} -> {end_bone}")
            return
        except TypeError:
            try:
                method(chain_name, start_bone, end_bone)
                log(f"Created chain {chain_name}: {start_bone} -> {end_bone}")
                created_log.append(f"{chain_name}: {start_bone} -> {end_bone}")
                return
            except TypeError:
                pass

    chain_class = find_class("RetargetChainSettings", "IKRigRetargetChain")
    method = getattr(controller, "set_retarget_chain", None)
    if chain_class and method:
        chain = chain_class()
        for attr, value in (
            ("chain_name", chain_name),
            ("start_bone", start_bone),
            ("end_bone", end_bone),
            ("ik_goal_name", ""),
        ):
            if hasattr(chain, attr):
                setattr(chain, attr, value)
        method(chain)
        log(f"Created chain {chain_name}: {start_bone} -> {end_bone}")
        created_log.append(f"{chain_name}: {start_bone} -> {end_bone}")
        return

    raise RuntimeError(
        "Could not add retarget chains. Expected controller.add_retarget_chain(...) "
        "or controller.set_retarget_chain(...)."
    )


def setup_ik_rig(
    ik_rig_path: str,
    skeletal_mesh_path: str,
    chains: dict[str, tuple[str, str]],
    created_log: list[str],
    skeletal_mesh_asset=None,
):
    skeletal_mesh = skeletal_mesh_asset if skeletal_mesh_asset is not None else load_required_asset(skeletal_mesh_path)
    chains = choose_chains_for_mesh(
        skeletal_mesh,
        chains,
        SOURCE_CHAIN_CANDIDATES if skeletal_mesh_path == SOURCE_SKELETAL_MESH else None,
    )
    ik_rig = create_asset_if_missing(
        ik_rig_path,
        "IKRigDefinition",
        ("IKRigDefinitionFactory", "IKRigDefinitionFactoryNew"),
    )

    controller = get_ik_rig_controller(ik_rig)
    set_preview_mesh(controller, skeletal_mesh)
    remove_all_retarget_chains(controller)
    set_retarget_root(controller, "pelvis")

    for chain_name, (start_bone, end_bone) in chains.items():
        add_retarget_chain(controller, chain_name, start_bone, end_bone, created_log)

    save_asset(ik_rig_path)
    save_loaded_asset(ik_rig)
    return ik_rig


def get_retargeter_controller(retargeter):
    controller_class = find_class("IKRetargeterController")
    if controller_class is None:
        raise RuntimeError("unreal.IKRetargeterController is not available. Enable the IK Rig plugin.")

    method = getattr(controller_class, "get_controller", None)
    if method:
        return method(retargeter)

    raise RuntimeError("Could not get IK Retargeter controller. Expected IKRetargeterController.get_controller().")


def set_retargeter_rig(controller, side: str, ik_rig) -> bool:
    direct_names = {
        "source": ("set_source_ik_rig", "set_source_rig"),
        "target": ("set_target_ik_rig", "set_target_rig"),
    }[side]
    for method_name in direct_names:
        method = getattr(controller, method_name, None)
        if method:
            method(ik_rig)
            log(f"Set {side} IK Rig: {ik_rig.get_name()}")
            return True

    enum_class = find_class("RetargetSourceOrTarget")
    method = getattr(controller, "set_ik_rig", None)
    if enum_class and method:
        enum_value = getattr(enum_class, side.upper())
        method(enum_value, ik_rig)
        log(f"Set {side} IK Rig: {ik_rig.get_name()}")
        return True

    warn(f"Could not set {side} IK rig via controller. Falling back to asset properties.")
    return False


def force_set_retargeter_asset_references(retargeter, source_ik_rig, target_ik_rig) -> None:
    """Fallback for UE builds where controller assignment is partial or stale."""
    assignments = [
        ("source_ik_rig_asset", source_ik_rig),
        ("target_ik_rig_asset", target_ik_rig),
        ("source_ik_rig", source_ik_rig),
        ("target_ik_rig", target_ik_rig),
        ("source_ik_rig_definition", source_ik_rig),
        ("target_ik_rig_definition", target_ik_rig),
    ]
    for prop_name, value in assignments:
        try:
            retargeter.set_editor_property(prop_name, value)
            log(f"Forced retargeter property {prop_name}: {value.get_path_name()}")
        except Exception:
            pass


def call_with_candidate_args(obj, method_name: str, candidates, label: str) -> bool:
    method = getattr(obj, method_name, None)
    if not method:
        return False
    for args in candidates:
        try:
            method(*args)
            log(f"{label}: called {method_name}{args}")
            return True
        except Exception as exc:
            warn(f"{label}: {method_name}{args} failed: {exc}")
    return False


def disable_root_motion_remap_ops(controller) -> None:
    """Disable Root Motion Remap ops that keep stale None root/pelvis values.

    The clean RTMPose test is intentionally chain-retarget only for now. Root
    motion can be brought back later, but these stale ops create noisy warnings
    and can confuse first-pass validation.
    """
    get_num = getattr(controller, "get_num_retarget_ops", None)
    get_name = getattr(controller, "get_op_name", None)
    if not get_num or not get_name:
        return

    try:
        count = int(get_num())
    except Exception as exc:
        warn(f"Could not inspect retarget op stack count: {exc}")
        return

    root_motion_indices = []
    for index in range(count):
        try:
            op_name = str(get_name(index))
        except Exception:
            op_name = ""
        lowered = op_name.replace(" ", "").replace("_", "").lower()
        if "rootmotion" in lowered or ("root" in lowered and "motion" in lowered):
            root_motion_indices.append((index, op_name))

    if not root_motion_indices:
        log("No Root Motion Remap op found to disable.")
        return

    set_enabled = getattr(controller, "set_retarget_op_enabled", None)
    remove_op = getattr(controller, "remove_retarget_op", None)
    get_op_controller = getattr(controller, "get_op_controller", None)

    for index, op_name in reversed(root_motion_indices):
        disabled = False

        if get_op_controller:
            for key in (index, op_name):
                try:
                    op_controller = get_op_controller(key)
                    for prop_name, value in (
                        ("source_root_bone", "root"),
                        ("target_root_bone", "root"),
                        ("target_pelvis_bone", "pelvis"),
                        ("root_bone", "root"),
                        ("pelvis_bone", "pelvis"),
                        ("enabled", False),
                    ):
                        try:
                            op_controller.set_editor_property(prop_name, value)
                            log(f"Set {op_name}.{prop_name}: {value}")
                        except Exception:
                            pass
                except Exception:
                    pass

        if set_enabled:
            for key in (index, op_name):
                try:
                    set_enabled(key, False)
                    log(f"Disabled retarget op: {op_name or index}")
                    disabled = True
                    break
                except Exception as exc:
                    warn(f"Could not disable retarget op {op_name or index} with key {key}: {exc}")

        # If this UE build refuses to disable it, removing the Root Motion Remap
        # op is safer than leaving stale None root fields in a body-only test.
        if not disabled and remove_op:
            for key in (index, op_name):
                try:
                    remove_op(key)
                    log(f"Removed retarget op: {op_name or index}")
                    disabled = True
                    break
                except Exception as exc:
                    warn(f"Could not remove retarget op {op_name or index} with key {key}: {exc}")


def set_retargeter_roots_and_ops(controller, retargeter, source_ik_rig, target_ik_rig) -> None:
    """Patch stale op-stack settings that show up as root/IKRig=None warnings."""
    enum_class = find_class("RetargetSourceOrTarget")
    source_enum = getattr(enum_class, "SOURCE", None) if enum_class else None
    target_enum = getattr(enum_class, "TARGET", None) if enum_class else None

    # Make every op use the currently assigned IK rigs. UE 5.7 exposes this.
    # Do source and target as separate calls; one successful call should not
    # prevent the other side from being assigned.
    if source_enum is not None:
        call_with_candidate_args(
            controller,
            "assign_ik_rig_to_all_ops",
            ((source_enum, source_ik_rig),),
            "Assign SOURCE IK Rig to ops",
        )
    if target_enum is not None:
        call_with_candidate_args(
            controller,
            "assign_ik_rig_to_all_ops",
            ((target_enum, target_ik_rig),),
            "Assign TARGET IK Rig to ops",
        )
    call_with_candidate_args(
        controller,
        "assign_ik_rig_to_all_ops",
        ((source_ik_rig,), (target_ik_rig,), ()),
        "Assign IK Rig to ops fallback",
    )
    disable_root_motion_remap_ops(controller)

    # Retargeter/root names are stored differently across versions. Try common
    # direct controller setters first.
    for method_name in (
        "set_source_root_bone",
        "set_target_root_bone",
        "set_root_bone",
        "set_source_root",
        "set_target_root",
        "set_root",
    ):
        call_with_candidate_args(
            controller,
            method_name,
            (
                ("root",),
                ("pelvis",),
                (source_enum, "root"),
                (target_enum, "root"),
                (source_enum, "pelvis"),
                (target_enum, "pelvis"),
            ),
            "Set retargeter root",
        )

    for method_name in ("set_target_pelvis_bone", "set_pelvis_bone", "set_target_pelvis"):
        call_with_candidate_args(
            controller,
            method_name,
            (("pelvis",), (target_enum, "pelvis")),
            "Set retargeter pelvis",
        )

    # Direct asset-property fallback for Root Motion Remap / IK Goal ops.
    root_assignments = [
        ("source_root_bone", "root"),
        ("target_root_bone", "root"),
        ("target_pelvis_bone", "pelvis"),
        ("source_root", "root"),
        ("target_root", "root"),
        ("target_pelvis", "pelvis"),
        ("root_bone", "root"),
        ("pelvis_bone", "pelvis"),
    ]
    for prop_name, value in root_assignments:
        try:
            retargeter.set_editor_property(prop_name, value)
            log(f"Forced retargeter property {prop_name}: {value}")
        except Exception:
            pass

    # If root motion remapping is optional in this UE version, turn it off for
    # this first clean pass. We can re-enable root motion later once body
    # retargeting is stable.
    for prop_name, value in (
        ("enable_root_motion", False),
        ("enable_root_motion_remap", False),
        ("root_motion_enabled", False),
        ("use_root_motion", False),
        ("copy_root_motion", False),
        ("root_motion_remap", False),
    ):
        try:
            retargeter.set_editor_property(prop_name, value)
            log(f"Disabled retargeter property {prop_name}")
        except Exception:
            pass

    # Some warnings come from nested op-stack UObjects. If exposed, walk them and
    # fill any obvious root/pelvis/IKRig properties.
    op_containers = []
    for prop_name in ("op_stack", "ops", "retarget_ops", "retargeter_ops", "global_settings"):
        try:
            value = retargeter.get_editor_property(prop_name)
            op_containers.append((prop_name, value))
        except Exception:
            pass
    for getter_name in ("get_retarget_ops", "get_ops", "get_op_stack"):
        getter = getattr(controller, getter_name, None)
        if getter:
            try:
                op_containers.append((getter_name, getter()))
            except Exception as exc:
                warn(f"{getter_name} failed: {exc}")

    for container_name, container in op_containers:
        try:
            ops = list(container)
        except Exception:
            ops = [container]
        for op in ops:
            for prop_name, value in (
                ("source_ik_rig_asset", source_ik_rig),
                ("target_ik_rig_asset", target_ik_rig),
                ("source_ik_rig", source_ik_rig),
                ("target_ik_rig", target_ik_rig),
                ("ik_rig_asset", target_ik_rig),
                ("ik_rig", target_ik_rig),
                ("source_root_bone", "root"),
                ("target_root_bone", "root"),
                ("target_pelvis_bone", "pelvis"),
                ("root_bone", "root"),
                ("pelvis_bone", "pelvis"),
                ("enable_root_motion", False),
                ("enable_root_motion_remap", False),
                ("root_motion_enabled", False),
                ("enabled", False) if "root" in op.get_class().get_name().lower() else ("__skip__", None),
            ):
                if prop_name == "__skip__":
                    continue
                try:
                    op.set_editor_property(prop_name, value)
                    shown = value.get_path_name() if hasattr(value, "get_path_name") else value
                    log(f"Forced op {container_name}.{prop_name}: {shown}")
                except Exception:
                    pass

    methods = [
        name for name in dir(controller)
        if "op" in name.lower() or "root" in name.lower() or "pelvis" in name.lower() or "rig" in name.lower()
    ]
    log(f"Retargeter controller op/root/rig methods: {methods}")


def set_chain_mapping(controller, source_chain: str, target_chain: str) -> None:
    # UE versions disagree about whether mappings are source->target or
    # target->source. Try the known spellings both ways, then fall back to
    # same-name auto mapping.
    attempts = (
        ("set_retarget_chain_mapping", (source_chain, target_chain)),
        ("set_retarget_chain_mapping", (target_chain, source_chain)),
        ("set_chain_mapping", (source_chain, target_chain)),
        ("set_chain_mapping", (target_chain, source_chain)),
        ("set_source_chain_mapping", (target_chain, source_chain)),
        ("set_source_chain_for_target_chain", (target_chain, source_chain)),
        ("set_source_chain", (target_chain, source_chain)),
    )
    for method_name, args in attempts:
        method = getattr(controller, method_name, None)
        if method:
            try:
                method(*args)
                log(f"Mapped {source_chain} -> {target_chain} via {method_name}{args}")
                CREATED_CHAIN_MAPPINGS.append(f"{source_chain} -> {target_chain}")
                return
            except Exception as exc:
                warn(f"{method_name}{args} failed: {exc}")
    warn(f"Could not explicitly map {source_chain} -> {target_chain}. Relying on same-name auto mapping.")


def enum_value_by_name(enum_class_name: str, *candidate_names):
    enum_class = find_class(enum_class_name)
    if enum_class is None:
        return None
    for name in candidate_names:
        value = getattr(enum_class, name, None)
        if value is not None:
            return value
    return None


def set_chain_translation_none(controller) -> None:
    """Keep retarget chains rotational for the clean dummy-to-knight pass."""
    get_settings = getattr(controller, "get_retarget_chain_settings", None)
    set_settings = getattr(controller, "set_retarget_chain_settings", None)
    if not get_settings or not set_settings:
        warn("Could not set chain translation mode: retargeter chain settings API unavailable.")
        return

    translation_none = (
        enum_value_by_name("RetargetTranslationMode", "NONE", "None_", "NONE_")
        or enum_value_by_name("ERetargetTranslationMode", "NONE", "None_", "NONE_")
        or enum_value_by_name("IKRetargetTranslationMode", "NONE", "None_", "NONE_")
    )

    for _source_chain, target_chain in CHAIN_MAP.items():
        try:
            settings = get_settings(target_chain)
        except Exception as exc:
            warn(f"Could not read chain settings for {target_chain}: {exc}")
            continue

        changed = False
        for prop_name, value in (
            ("translation_mode", translation_none),
            ("translation_alpha", 0.0),
            ("blend_to_source", 0.0),
            ("blend_to_source_weights", 0.0),
            ("static_offset", unreal.Vector(0.0, 0.0, 0.0)),
            ("enable_translation", False),
            ("copy_translation", False),
        ):
            if value is None:
                continue
            try:
                settings.set_editor_property(prop_name, value)
                changed = True
                log(f"Set {target_chain}.{prop_name}: {value}")
            except Exception:
                pass

        if changed:
            for args in ((target_chain, settings), (settings,)):
                try:
                    set_settings(*args)
                    log(f"Saved chain settings for {target_chain}")
                    break
                except Exception as exc:
                    warn(f"Could not save chain settings for {target_chain} with args {args}: {exc}")


def auto_map_retargeter_chains(controller) -> None:
    for method_name in ("auto_map_chains", "auto_map_retarget_chains", "auto_align_all_bones"):
        method = getattr(controller, method_name, None)
        if method:
            try:
                method()
                log(f"Ran retargeter {method_name}()")
                return
            except Exception as exc:
                warn(f"{method_name}() failed: {exc}")
    methods = [name for name in dir(controller) if "chain" in name.lower() or "map" in name.lower() or "rig" in name.lower()]
    warn(f"No compatible auto-map method found. Retargeter controller relevant methods: {methods}")


def setup_retargeter(retargeter_path: str, source_ik_rig, target_ik_rig) -> None:
    retargeter = create_asset_if_missing(
        retargeter_path,
        "IKRetargeter",
        ("IKRetargetFactory", "IKRetargeterFactory", "IKRetargeterFactoryNew"),
    )
    controller = get_retargeter_controller(retargeter)

    set_retargeter_rig(controller, "source", source_ik_rig)
    set_retargeter_rig(controller, "target", target_ik_rig)
    force_set_retargeter_asset_references(retargeter, source_ik_rig, target_ik_rig)
    set_retargeter_roots_and_ops(controller, retargeter, source_ik_rig, target_ik_rig)
    auto_map_retargeter_chains(controller)

    for source_chain, target_chain in CHAIN_MAP.items():
        set_chain_mapping(controller, source_chain, target_chain)
    set_chain_translation_none(controller)
    disable_root_motion_remap_ops(controller)

    save_loaded_asset(retargeter)
    save_asset(retargeter_path)


def parse_overrides() -> None:
    global SOURCE_SKELETAL_MESH, TARGET_SKELETAL_MESH, SOURCE_IK_RIG, TARGET_IK_RIG, IK_RETARGETER

    args = sys.argv[1:]
    pairs = {}
    idx = 0
    while idx < len(args):
        key = args[idx]
        if key.startswith("--") and idx + 1 < len(args):
            pairs[key[2:]] = args[idx + 1]
            idx += 2
        else:
            idx += 1

    SOURCE_SKELETAL_MESH = pairs.get("source-mesh", SOURCE_SKELETAL_MESH)
    TARGET_SKELETAL_MESH = pairs.get("target-mesh", TARGET_SKELETAL_MESH)
    SOURCE_IK_RIG = pairs.get("source-ikrig", SOURCE_IK_RIG)
    TARGET_IK_RIG = pairs.get("target-ikrig", TARGET_IK_RIG)
    IK_RETARGETER = pairs.get("retargeter", IK_RETARGETER)


def main() -> None:
    parse_overrides()
    log("Starting Octopi IK Rig / Retargeter setup")
    log(f"Source mesh: {SOURCE_SKELETAL_MESH}")
    log(f"Target mesh: {TARGET_SKELETAL_MESH}")
    log("Root chain is intentionally omitted to avoid 'chain too short' normalization warnings.")

    CREATED_SOURCE_CHAINS.clear()
    CREATED_TARGET_CHAINS.clear()
    CREATED_CHAIN_MAPPINGS.clear()

    target_mesh = find_knight4_skeletal_mesh()

    source_ik_rig = setup_ik_rig(SOURCE_IK_RIG, SOURCE_SKELETAL_MESH, SOURCE_CHAINS, CREATED_SOURCE_CHAINS)
    target_ik_rig = setup_ik_rig(
        TARGET_IK_RIG,
        TARGET_SKELETAL_MESH,
        TARGET_CHAINS,
        CREATED_TARGET_CHAINS,
        skeletal_mesh_asset=target_mesh,
    )
    setup_retargeter(IK_RETARGETER, source_ik_rig, target_ik_rig)

    log("SUMMARY")
    log(f"SOURCE IK RIG PATH: {SOURCE_IK_RIG}")
    log(f"TARGET IK RIG PATH: {TARGET_IK_RIG}")
    log(f"RETARGETER PATH: {IK_RETARGETER}")
    log(f"CREATED SOURCE CHAINS: {CREATED_SOURCE_CHAINS}")
    log(f"CREATED TARGET CHAINS: {CREATED_TARGET_CHAINS}")
    log(f"CREATED CHAIN MAPPINGS: {CREATED_CHAIN_MAPPINGS}")
    log("Done")


if __name__ == "__main__":
    main()
