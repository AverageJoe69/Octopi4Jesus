param(
  [string]$Folder = "outputs\gold_mocap_full_217f_mesh_dummy_fbx"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$base = Join-Path $root $Folder
$sourcePath = Join-Path $base "skeleton_animation.json"
$jsonOut = Join-Path $base "skeleton_points_through_time.json"
$txtOut = Join-Path $base "skeleton_points_through_time.txt"

if (-not (Test-Path -LiteralPath $sourcePath)) {
  throw "Missing source animation JSON: $sourcePath"
}

$source = Get-Content -Raw -LiteralPath $sourcePath | ConvertFrom-Json
$fps = [double]$source.fps
$frames = @($source.frames)
$edges = @($source.edges)

$jointNames = @()
if ($frames.Count -gt 0) {
  $jointNames = @(
    $frames[0].PSObject.Properties |
      Where-Object { $_.Name -ne "frame" } |
      ForEach-Object { $_.Name }
  )
}

$reviewFrames = New-Object System.Collections.Generic.List[object]
for ($i = 0; $i -lt $frames.Count; $i++) {
  $frameObj = $frames[$i]
  $points = [ordered]@{}

  foreach ($joint in $jointNames) {
    $value = $frameObj.$joint
    if ($null -eq $value) {
      $points[$joint] = $null
      continue
    }

    $coords = @($value)
    if ($coords.Count -lt 3) {
      $points[$joint] = $null
      continue
    }

    $points[$joint] = [ordered]@{
      x = [double]$coords[0]
      y = [double]$coords[1]
      z = [double]$coords[2]
    }
  }

  $reviewFrames.Add([ordered]@{
    frame_index = $i
    frame_name = [string]$frameObj.frame
    time_seconds = [math]::Round($i / $fps, 6)
    points = $points
  })
}

$review = [ordered]@{
  description = "Animated RTMPose multi-view skeleton points through time for GPT review."
  source = "skeleton_animation.json"
  fps = $fps
  frame_count = $frames.Count
  units = "export units used by the gold FBX; current gold export is 10x scaled for UE testing"
  coordinate_frame = $source.coordinate_frame
  joints = $jointNames
  edges = $edges
  frames = $reviewFrames
}

$review | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $jsonOut -Encoding UTF8

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("Animated RTMPose multi-view skeleton points through time")
$lines.Add("Source: skeleton_animation.json")
$lines.Add("FPS: $fps")
$lines.Add("Frame count: $($frames.Count)")
$lines.Add("Units: export units used by the gold FBX; current gold export is 10x scaled for UE testing")
$lines.Add("Coordinate frame: $($source.coordinate_frame)")
$lines.Add("")
$lines.Add("Skeleton edges:")
foreach ($edge in $edges) {
  $edgeVals = @($edge)
  if ($edgeVals.Count -ge 2) {
    $lines.Add("  $($edgeVals[0]) -> $($edgeVals[1])")
  }
}
$lines.Add("")
$lines.Add("Frames:")

foreach ($frame in $reviewFrames) {
  $lines.Add("")
  $lines.Add("frame_index=$($frame.frame_index) frame_name=$($frame.frame_name) time_seconds=$($frame.time_seconds)")
  foreach ($joint in $jointNames) {
    $point = $frame.points[$joint]
    if ($null -eq $point) {
      $lines.Add("  ${joint}: null")
    } else {
      $lines.Add(("  {0}: x={1:F6}, y={2:F6}, z={3:F6}" -f $joint, $point.x, $point.y, $point.z))
    }
  }
}

$lines | Set-Content -LiteralPath $txtOut -Encoding UTF8

Write-Host "Wrote $jsonOut"
Write-Host "Wrote $txtOut"
