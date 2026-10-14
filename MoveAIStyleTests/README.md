# Octopi Gold Mocap Path

This folder is now the main Octopi markerless mocap path.
It does not use stereo depth, FoundationStereo, Isaac ROS, CREStereo, or left-camera stereo mates.

The gold path is:

1. Load one synchronized frame from `Cam1` through `Cam8`.
2. Detect 2D human pose/keypoints in each RGB view.
3. Triangulate matching joints with the known Unreal camera intrinsics/extrinsics.
4. Stabilize the sequence temporally.
5. Export a Blender mesh dummy animation and FBX.

This is not dense reconstruction. It is a Move.ai-style baseline:

`8 RGB views -> 2D keypoints -> multi-view triangulation -> sparse 3D skeleton`

## Camera Assumptions

The script reads camera poses from:

`StereoMaskFusion/data/octopi_cameras_named.json`

Current UE intrinsics:

```text
fx = 782.222
fy = 792.000
cx = 960
cy = 540
resolution = 1920x1080
```

Camera locations in the JSON are Unreal centimetres and are converted to metres.

Only the original/right cameras are used:

```text
cam1 cam2 cam3 cam4 cam5 cam6 cam7 cam8
```

The `_L` cameras are ignored for this test.

## Pose Backend

Use RTMPose + RTMDet. YOLO is no longer the main route.

## RTMPose Environment

The RTMPose test uses an isolated venv:

```text
C:\OCTOPI_Pipeline\venvs\rtmpose
```

Installed stack:

```text
torch 2.1.2+cu121
torchvision 0.16.2+cu121
mmcv 2.1.0
mmdet 3.2.0
mmpose 1.3.2
```

On Windows, this venv also contains a tiny local patch to YAPF's bundled grammar
cache writer to avoid a temp-file import stall.

## Gold Export

Current gold output:

```text
outputs/gold_mocap_full_217f_mesh_dummy_fbx/rtmpose_skeleton_animation.fbx
```

It is a Blender mesh dummy export:

- 217 frames, `0000` to `0216`
- 60 fps
- 10x scale for UE testing
- temporal multi-view RTMPose triangulation
- fixed bone lengths during export, so forearms should not stretch when the sword confuses wrist/forearm estimates

Regenerate the full FBX:

```powershell
.\MoveAIStyleTests\export_gold_fbx.ps1
```

The script writes:

```text
outputs/gold_mocap_full_217f_mesh_dummy_fbx/
  rtmpose_skeleton_animation.fbx
  rtmpose_skeleton_animation.blend
  OctopiDummy_in_place.fbx
  OctopiDummy_in_place.blend
  OctopiDummy_root_motion.fbx
  OctopiDummy_root_motion.blend
  OctopiDummy_UE_native.fbx
  OctopiDummy_UE_native.blend
  skeleton_animation.json
  skeleton_points_through_time.json
  skeleton_points_through_time.txt
  make_blender_fbx.py
  make_armature_fbx_blender.py
```

Use `OctopiDummy_in_place.fbx` first for Unreal retargeting. It contains one
skinned proxy mesh, one Armature/Skeleton, and one animation take, with no
separate joint or edge mesh objects.

Use `OctopiDummy_root_motion.fbx` when testing root motion. Both armature
exports are root-normalized: the armature object is not animated, the root bone
starts at the ground origin, and frame 0 is ground-aligned from the lowest ankle.

Use `OctopiDummy_UE_native.fbx` when you want to skip Unreal retargeting. It
uses Unreal/Knight-style bone names directly:

```text
root
pelvis
spine_01
spine_02
spine_03
neck_01
head
upperarm_l
lowerarm_l
hand_l
upperarm_r
lowerarm_r
hand_r
thigh_l
calf_l
foot_l
thigh_r
calf_r
foot_r
```

If that import collapses the mesh, use the Knight4 bind-pose path instead. It
exports the exact `SK_Knight4` skeleton from Unreal, then bakes RTMPose motion
onto that real skeleton without changing bind-pose translations or extra bones.

First run this inside Unreal Editor Python:

```python
exec(open(r"C:/OCTOPI_Pipeline/UnrealTools/export_sk_knight4_bind_fbx.py").read())
```

Then run:

```powershell
C:\OCTOPI_Pipeline\venvs\rtmpose\Scripts\python.exe MoveAIStyleTests\make_knight4_animation_fbx.py `
  --folder outputs\gold_mocap_full_217f_mesh_dummy_fbx
```

This writes:

```text
outputs/gold_mocap_full_217f_mesh_dummy_fbx/OctopiDummy_SK_Knight4_anim.fbx
```

Import that in Unreal as animation for `SK_Knight4`.

The Knight4 animation baker is not a raw frame-by-frame pose converter. It first
stabilizes the RTMPose joint trajectory, reconstructs elbows/knees as two-bone
hinges with fixed segment lengths, stabilizes foot forward/up directions, then
solves parent-relative bone rotations with full orientation bases.

## Manual Two-Step Export

The PowerShell script above runs both steps. If needed, run them manually:

```powershell
C:\OCTOPI_Pipeline\venvs\rtmpose\Scripts\python.exe MoveAIStyleTests\rtmpose_temporal_mocap.py `
  --data StereoMaskFusion\data `
  --frames 0000:0216 `
  --out outputs\gold_mocap_temporal_source `
  --cameras StereoMaskFusion\data\octopi_cameras_named.json `
  --device cuda:0 `
  --det-conf 0.15 `
  --joint-conf 0.20 `
  --min-views 3 `
  --ransac-threshold-px 16 `
  --max-reprojection-error-px 24 `
  --prediction-gate-m 0.28 `
  --prediction-weight 8 `
  --hold-max-frames 8 `
  --smooth-alpha 0.65 `
  --save-debug-images false
```

```powershell
C:\OCTOPI_Pipeline\venvs\rtmpose\Scripts\python.exe MoveAIStyleTests\export_blender_animation.py `
  --input outputs\gold_mocap_temporal_source `
  --out outputs\gold_mocap_full_217f_mesh_dummy_fbx `
  --fps 60 `
  --coordinate-mode blender `
  --scale 10 `
  --lock-bone-lengths true `
  --bone-length-iters 12
```

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --python outputs\gold_mocap_full_217f_mesh_dummy_fbx\make_blender_fbx.py
```

To build only the retargetable armature FBXs from an existing
`skeleton_animation.json`:

```powershell
C:\OCTOPI_Pipeline\venvs\rtmpose\Scripts\python.exe MoveAIStyleTests\make_armature_fbx.py `
  --folder outputs\gold_mocap_full_217f_mesh_dummy_fbx `
  --name OctopiDummy
```

To build only the UE-native skeleton FBX:

```powershell
C:\OCTOPI_Pipeline\venvs\rtmpose\Scripts\python.exe MoveAIStyleTests\make_ue_native_fbx.py `
  --folder outputs\gold_mocap_full_217f_mesh_dummy_fbx
```

## Diagnostics

Use `debug_pose_frame.py` when a bad frame needs camera-by-camera overlays.
For example, frame `0068` is a useful stress test for arms/legs swapping.

If the armor/helmet confuses the human pose model, the debug overlays are still
the useful first diagnostic: they show which views and joints failed before
triangulation.
