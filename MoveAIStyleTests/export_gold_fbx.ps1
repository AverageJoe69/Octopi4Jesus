param(
  [string]$Frames = "0000:0216",
  [string]$Out = "outputs\gold_mocap_full_217f_mesh_dummy_fbx",
  [string]$Data = "StereoMaskFusion\data",
  [string]$Cameras = "StereoMaskFusion\data\octopi_cameras_named.json",
  [string]$Blender = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "venvs\rtmpose\Scripts\python.exe"

$env:MPLCONFIGDIR = Join-Path $root "venvs\rtmpose\matplotlib"
$env:TMP = Join-Path $root "venvs\rtmpose\tmp"
$env:TEMP = Join-Path $root "venvs\rtmpose\tmp"
New-Item -ItemType Directory -Force $env:MPLCONFIGDIR | Out-Null
New-Item -ItemType Directory -Force $env:TMP | Out-Null

& $python MoveAIStyleTests\rtmpose_temporal_mocap.py `
  --data $Data `
  --frames $Frames `
  --out "outputs\gold_mocap_temporal_source" `
  --cameras $Cameras `
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

& $python MoveAIStyleTests\export_blender_animation.py `
  --input "outputs\gold_mocap_temporal_source" `
  --out $Out `
  --fps 60 `
  --coordinate-mode blender `
  --scale 10 `
  --min-joint-confidence 0.0 `
  --max-reproj-error-px 999 `
  --fix-side-swaps false `
  --body-side-gate false `
  --arm-ik false `
  --outlier-clean false `
  --constraint-clean false `
  --lock-bone-lengths true `
  --bone-length-iters 12

& $Blender --background --python (Join-Path $Out "make_blender_fbx.py")

& (Join-Path $PSScriptRoot "export_points_for_gpt.ps1") -Folder $Out
& $python MoveAIStyleTests\make_armature_fbx.py `
  --folder $Out `
  --blender $Blender `
  --name OctopiDummy

& $python MoveAIStyleTests\make_ue_native_fbx.py `
  --folder $Out `
  --blender $Blender

Write-Host "Gold FBX written to: $(Join-Path $Out 'rtmpose_skeleton_animation.fbx')"
Write-Host "In-place armature FBX written to: $(Join-Path $Out 'OctopiDummy_in_place.fbx')"
Write-Host "Root-motion armature FBX written to: $(Join-Path $Out 'OctopiDummy_root_motion.fbx')"
Write-Host "UE-native FBX written to: $(Join-Path $Out 'OctopiDummy_UE_native.fbx')"
