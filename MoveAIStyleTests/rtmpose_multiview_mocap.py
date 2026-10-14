import argparse
import csv
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("venvs/rtmpose/matplotlib").resolve()))
os.environ.setdefault("TMP", str(Path("venvs/rtmpose/tmp").resolve()))
os.environ.setdefault("TEMP", str(Path("venvs/rtmpose/tmp").resolve()))

import cv2
import numpy as np

from multiview_mono_pose import (
    COCO17_NAMES,
    draw_keypoints,
    draw_reprojection,
    image_path,
    load_camera_data,
    save_skeleton_ply,
    triangulate_skeleton,
    write_report,
)


DEFAULT_DET_CKPT = (
    "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/"
    "rtmdet_m_8xb32-100e_coco-obj365-person-235e8209.pth"
)
DEFAULT_POSE_CKPT = (
    "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/"
    "rtmpose-m_simcc-coco_pt-aic-coco_420e-256x192-d8dd5ca4_20230127.pth"
)


def parse_args():
    parser = argparse.ArgumentParser(description="RTMPose 8-view mono mocap triangulation test")
    parser.add_argument("--data", default="StereoMaskFusion/data")
    parser.add_argument("--frame", default="0000", help="Single frame id, e.g. 0000")
    parser.add_argument("--frames", default="", help="Optional range/list, e.g. 0000:0010 or 0000,0001")
    parser.add_argument("--out", default="outputs/moveai_style_test")
    parser.add_argument("--cameras", default="StereoMaskFusion/data/octopi_cameras_named.json")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--fx", type=float, default=None)
    parser.add_argument("--fy", type=float, default=None)
    parser.add_argument("--cx", type=float, default=None)
    parser.add_argument("--cy", type=float, default=None)
    parser.add_argument("--det-config", default="")
    parser.add_argument("--det-checkpoint", default=DEFAULT_DET_CKPT)
    parser.add_argument("--pose-config", default="")
    parser.add_argument("--pose-checkpoint", default=DEFAULT_POSE_CKPT)
    parser.add_argument("--det-conf", type=float, default=0.15)
    parser.add_argument("--joint-conf", type=float, default=0.20)
    parser.add_argument("--nms-thr", type=float, default=0.30)
    parser.add_argument("--min-views", type=int, default=2)
    parser.add_argument("--ransac-threshold-px", type=float, default=20.0)
    parser.add_argument("--ransac-iters", type=int, default=128)
    parser.add_argument("--max-reprojection-error-px", type=float, default=40.0)
    parser.add_argument("--temporal-smoothing", default="true")
    parser.add_argument("--smoothing-alpha", type=float, default=0.65)
    parser.add_argument("--ply-bone-radius", type=float, default=0.015)
    return parser.parse_args()


def str_to_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_frames(frame, frames):
    if not frames.strip():
        return [frame]
    value = frames.strip()
    if ":" in value:
        start, end = value.split(":", 1)
        width = max(len(start), len(end))
        return [f"{idx:0{width}d}" for idx in range(int(start), int(end) + 1)]
    return [part.strip() for part in value.split(",") if part.strip()]


def resolve_default_configs():
    import mmpose

    root = Path(mmpose.__file__).parent / ".mim"
    det_config = root / "demo" / "mmdetection_cfg" / "rtmdet_m_640-8xb32_coco-person.py"
    pose_config = root / "configs" / "body_2d_keypoint" / "rtmpose" / "coco" / "rtmpose-m_8xb256-420e_coco-256x192.py"
    return str(det_config), str(pose_config)


def init_rtmpose(args):
    from mmdet.apis import init_detector
    from mmpose.apis import init_model as init_pose_estimator
    from mmpose.utils import adapt_mmdet_pipeline

    default_det_config, default_pose_config = resolve_default_configs()
    det_config = args.det_config or default_det_config
    pose_config = args.pose_config or default_pose_config

    detector = init_detector(det_config, args.det_checkpoint, device=args.device)
    detector.cfg = adapt_mmdet_pipeline(detector.cfg)
    pose_model = init_pose_estimator(pose_config, args.pose_checkpoint, device=args.device)
    return detector, pose_model


def best_pose_from_instances(pose_results, bbox_scores):
    if not pose_results:
        return None

    candidates = []
    for idx, result in enumerate(pose_results):
        inst = result.pred_instances
        keypoints = np.asarray(inst.keypoints, dtype=np.float64)
        scores = np.asarray(inst.keypoint_scores, dtype=np.float64)
        if keypoints.ndim == 3:
            keypoints = keypoints[0]
        if scores.ndim == 2:
            scores = scores[0]
        valid = scores > 0.05
        if not np.any(valid):
            continue
        span = keypoints[valid]
        area = max(1.0, float((span[:, 0].max() - span[:, 0].min()) * (span[:, 1].max() - span[:, 1].min())))
        bbox_score = float(bbox_scores[idx]) if idx < len(bbox_scores) else 1.0
        score = bbox_score * float(np.mean(scores[valid])) * area
        candidates.append((score, keypoints, scores, bbox_score))

    if not candidates:
        return None
    _, keypoints, scores, bbox_score = max(candidates, key=lambda item: item[0])
    return {"xy": keypoints, "conf": scores, "person_conf": bbox_score}


def detect_one(detector, pose_model, image, det_conf, nms_thr):
    from mmdet.apis import inference_detector
    from mmpose.apis import inference_topdown
    from mmpose.evaluation.functional import nms

    det_result = inference_detector(detector, image)
    pred = det_result.pred_instances.cpu().numpy()
    bboxes = np.concatenate((pred.bboxes, pred.scores[:, None]), axis=1)
    bboxes = bboxes[np.logical_and(pred.labels == 0, pred.scores > det_conf)]
    if len(bboxes) == 0:
        return None
    keep = nms(bboxes, nms_thr)
    bboxes = bboxes[keep]
    bbox_scores = bboxes[:, 4].copy()
    pose_results = inference_topdown(pose_model, image, bboxes[:, :4])
    return best_pose_from_instances(pose_results, bbox_scores)


def detect_all(detector, pose_model, images, det_conf, nms_thr):
    detections = {}
    for cam_id, image in images.items():
        detections[cam_id] = detect_one(detector, pose_model, image, det_conf, nms_thr)
    return detections


def smooth_skeleton(prev, current, alpha):
    if prev is None:
        return current
    smoothed = {}
    for name, joint in current.items():
        new_joint = dict(joint)
        point = np.asarray(joint["world_m"], dtype=np.float64)
        if name in prev:
            old = np.asarray(prev[name]["world_m"], dtype=np.float64)
            point = alpha * point + (1.0 - alpha) * old
            new_joint["world_m"] = point.tolist()
            new_joint["smoothed"] = True
        else:
            new_joint["smoothed"] = False
        smoothed[name] = new_joint
    return smoothed


def process_frame(args, frame, detector, pose_model, cameras, k, prev_skeleton):
    frame_out = Path(args.out) / f"frame{frame}"
    frame_out.mkdir(parents=True, exist_ok=True)

    images = {}
    for cam_id in range(1, 9):
        path = image_path(args.data, cam_id, frame)
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"Missing frame for cam{cam_id}: {path}")
        images[cam_id] = image

    detections = detect_all(detector, pose_model, images, args.det_conf, args.nms_thr)
    for cam_id, image in images.items():
        overlay = draw_keypoints(image, detections[cam_id], title=f"cam{cam_id:02d} RTMPose")
        cv2.imwrite(str(frame_out / f"keypoints_2d_cam{cam_id:02d}.png"), overlay)

    skeleton, rows = triangulate_skeleton(
        detections,
        cameras,
        joint_conf=args.joint_conf,
        min_views=args.min_views,
        threshold_px=args.ransac_threshold_px,
        iters=args.ransac_iters,
        max_error=args.max_reprojection_error_px,
    )

    if str_to_bool(args.temporal_smoothing):
        skeleton = smooth_skeleton(prev_skeleton, skeleton, args.smoothing_alpha)

    for cam_id, image in images.items():
        reproj = draw_reprojection(image, skeleton, cameras[cam_id])
        cv2.imwrite(str(frame_out / f"reprojected_3d_cam{cam_id:02d}.png"), reproj)

    metadata = {
        "frame": frame,
        "backend": "RTMPose",
        "detector": "RTMDet person",
        "intrinsics": {"fx": float(k[0, 0]), "fy": float(k[1, 1]), "cx": float(k[0, 2]), "cy": float(k[1, 2])},
        "coordinate_frame": "Unreal world metres",
        "joints": skeleton,
    }
    (frame_out / "skeleton_3d.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    save_skeleton_ply(frame_out / "skeleton_3d.ply", skeleton, args.ply_bone_radius)
    write_report(frame_out / "report.csv", rows)

    detected_cams = sum(1 for det in detections.values() if det is not None)
    ok_joints = sum(1 for row in rows if row["status"] == "ok")
    print(f"frame {frame}: detected cameras {detected_cams}/8, triangulated joints {ok_joints}/{len(COCO17_NAMES)}")
    for row in rows:
        if row["status"] == "ok":
            print(
                f"  {row['joint']}: cams={row['cameras_used']} "
                f"err={float(row['mean_reprojection_error_px']):.2f}px "
                f"xyz=({float(row['x_m']):.3f}, {float(row['y_m']):.3f}, {float(row['z_m']):.3f}) "
                f"conf={float(row['confidence']):.3f}"
            )
        else:
            print(f"  {row['joint']}: failed")
    return skeleton


def main():
    args = parse_args()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["TMP"]).mkdir(parents=True, exist_ok=True)

    cameras, k = load_camera_data(args.cameras, args.fx, args.fy, args.cx, args.cy)
    detector, pose_model = init_rtmpose(args)

    prev_skeleton = None
    for frame in parse_frames(args.frame, args.frames):
        prev_skeleton = process_frame(args, frame, detector, pose_model, cameras, k, prev_skeleton)

    print(f"wrote: {Path(args.out).resolve()}")


if __name__ == "__main__":
    main()
