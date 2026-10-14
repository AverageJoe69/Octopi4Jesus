import json
from pathlib import Path

import bpy
from mathutils import Vector

BASE = Path(r"C:\OCTOPI_Pipeline\outputs\gold_mocap_full_217f_mesh_dummy_fbx")
DATA = json.loads((BASE / "skeleton_animation.json").read_text())
FPS = DATA.get("fps", 30)
EDGES = DATA["edges"]
FRAMES = DATA["frames"]

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()
bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = len(FRAMES)
bpy.context.scene.render.fps = int(FPS)

mat_joint = bpy.data.materials.new("RTMPose_Joints")
mat_joint.diffuse_color = (1.0, 0.35, 0.02, 1.0)
mat_bone = bpy.data.materials.new("RTMPose_Bones")
mat_bone.diffuse_color = (1.0, 0.75, 0.05, 1.0)

joints = sorted({key for frame in FRAMES for key in frame.keys() if key != "frame"})
objects = {}
for joint in joints:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.055, location=(0, 0, 0))
    obj = bpy.context.object
    obj.name = joint
    obj.data.materials.append(mat_joint)
    objects[joint] = obj

def set_obj_location(obj, co, frame_idx):
    obj.location = (co[0], co[1], co[2])
    obj.keyframe_insert(data_path="location", frame=frame_idx)

for idx, frame in enumerate(FRAMES, start=1):
    for joint, obj in objects.items():
        if joint in frame:
            set_obj_location(obj, frame[joint], idx)

bone_objs = []
for a, b in EDGES:
    if a not in objects or b not in objects:
        continue
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.025, depth=1.0, location=(0, 0, 0))
    obj = bpy.context.object
    obj.name = f"{a}_to_{b}"
    obj.data.materials.append(mat_bone)
    bone_objs.append((obj, a, b))

def set_bone_transform(obj, a_co, b_co, frame_idx):
    a_vec = Vector((a_co[0], a_co[1], a_co[2]))
    b_vec = Vector((b_co[0], b_co[1], b_co[2]))
    vec = b_vec - a_vec
    length = vec.length
    if length < 1e-6:
        return
    obj.location = a_vec + vec * 0.5
    obj.rotation_euler = vec.to_track_quat("Z", "Y").to_euler()
    obj.scale = (1.0, 1.0, length)
    obj.keyframe_insert(data_path="location", frame=frame_idx)
    obj.keyframe_insert(data_path="rotation_euler", frame=frame_idx)
    obj.keyframe_insert(data_path="scale", frame=frame_idx)

for idx, frame in enumerate(FRAMES, start=1):
    for obj, a, b in bone_objs:
        if a not in frame or b not in frame:
            continue
        set_bone_transform(obj, frame[a], frame[b], idx)

bpy.ops.wm.save_as_mainfile(filepath=str(BASE / "rtmpose_skeleton_animation.blend"))
bpy.ops.export_scene.fbx(filepath=str(BASE / "rtmpose_skeleton_animation.fbx"), use_selection=False)
print(f"Saved {BASE / 'rtmpose_skeleton_animation.blend'}")
print(f"Saved {BASE / 'rtmpose_skeleton_animation.fbx'}")
