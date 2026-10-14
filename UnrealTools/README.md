# Octopi Unreal Tools

## IK Retarget Setup

Use this after importing the RTMPose dummy FBX into Unreal.

Script:

```text
UnrealTools/setup_octopi_ik_retarget.py
```

It creates or updates:

```text
IKR_RTMPoseDummy_Clean
IKR_Knight4_Clean
RTG_RTMPose_To_Knight4_Clean
```

The script removes bad auto-generated retarget chains and creates clean chains:

```text
Spine
Head
LeftArm
RightArm
LeftLeg
RightLeg
```

Source RTMPose chains:

```text
Spine: pelvis -> neck
Head: neck -> nose
LeftArm: left_shoulder -> left_wrist
RightArm: right_shoulder -> right_wrist
LeftLeg: left_hip -> left_ankle
RightLeg: right_hip -> right_ankle
```

Target knight chains:

```text
Spine: pelvis -> spine_03
Head: neck_01 -> head
LeftArm: upperarm_l -> hand_l
RightArm: upperarm_r -> hand_r
LeftLeg: thigh_l -> foot_l
RightLeg: thigh_r -> foot_r
```

Edit the asset paths at the top of the Python script:

```python
SOURCE_SKELETAL_MESH = "/Game/_GENERATED/joeconway/OctopiDummy_in_place"
TARGET_SKELETAL_MESH = "/Game/Characters/Knight4/SK_Knight4"

SOURCE_IK_RIG = "/Game/Octopi/RTMPose/IKR_RTMPoseDummy_Clean"
TARGET_IK_RIG = "/Game/Octopi/RTMPose/IKR_Knight4_Clean"
IK_RETARGETER = "/Game/Octopi/RTMPose/RTG_RTMPose_To_Knight4_Clean"
```

Run inside Unreal Editor Python:

```text
py C:/OCTOPI_Pipeline/UnrealTools/setup_octopi_ik_retarget.py
```

Or pass paths without editing:

```text
py C:/OCTOPI_Pipeline/UnrealTools/setup_octopi_ik_retarget.py --source-mesh /Game/_GENERATED/joeconway/OctopiDummy_in_place --target-mesh /Game/Characters/Knight4/SK_Knight4
```

The script does not touch the imported animation or rename imported assets.

## Export Knight4 Bind Pose

When building an animation-only FBX for the exact Knight4 skeleton, first export
the real bind pose from Unreal:

```python
exec(open(r"C:/OCTOPI_Pipeline/UnrealTools/export_sk_knight4_bind_fbx.py").read())
```

This writes:

```text
C:/OCTOPI_Pipeline/outputs/gold_mocap_full_217f_mesh_dummy_fbx/SK_Knight4_bindpose.fbx
```

Then run the Blender-side animation baker from PowerShell:

```powershell
C:\OCTOPI_Pipeline\venvs\rtmpose\Scripts\python.exe MoveAIStyleTests\make_knight4_animation_fbx.py `
  --folder outputs\gold_mocap_full_217f_mesh_dummy_fbx
```
