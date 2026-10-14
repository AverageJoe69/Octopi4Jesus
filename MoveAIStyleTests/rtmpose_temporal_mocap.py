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
    project_point,
    reprojection_errors,
    save_skeleton_ply,
    triangulate_dlt,
    write_report,
)
from rtmpose_multiview_mocap import detect_all, init_rtmpose, parse_frames


def parse_args():
    parser = argparse.ArgumentParser(description="Temporal RTMPose multi-view mocap with prediction-aware triangulation")
    parser.add_argument("--data", default="StereoMaskFusion/data")
    parser.add_argument("--frame", default="0000")
    parser.add_argument("--frames", default="0000:0099")
    parser.add_argument("--out", default="outputs/moveai_style_rtmpose_temporal_100f")
    parser.add_argument("--cameras", default="StereoMaskFusion/data/octopi_cameras_named.json")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--fx", type=float, default=None)
    parser.add_argument("--fy", type=float, default=None)
    parser.add_argument("--cx", type=float, default=None)
    parser.add_argument("--cy", type=float, default=None)
    parser.add_argument("--det-config", default="")
    parser.add_argument(
        "--det-checkpoint",
        default="https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/rtmdet_m_8xb32-100e_coco-obj365-person-235e8209.pth",
    )
    parser.add_argument("--pose-config", default="")
    parser.add_argument(
        "--pose-checkpoint",
        default="https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/rtmpose-m_simcc-coco_pt-aic-coco_420e-256x192-d8dd5ca4_20230127.pth",
    )
    parser.add_argument("--det-conf", type=float, default=0.15)
    parser.add_argument("--joint-conf", type=float, default=0.20)
    parser.add_argument("--nms-thr", type=float, default=0.30)
    parser.add_argument("--min-views", type=int, default=3)
    parser.add_argument("--ransac-threshold-px", type=float, default=18.0)
    parser.add_argument("--max-reprojection-error-px", type=float, default=28.0)
    parser.add_argument("--prediction-gate-m", type=float, default=0.45)
    parser.add_argument("--prediction-weight", type=float, default=6.0)
    parser.add_argument("--hold-max-frames", type=int, default=6)
    parser.add_argument("--smooth-alpha", type=float, default=0.72)
    parser.add_argument("--save-debug-images", default="true")
    return parser.parse_args()


def str_to_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def detection_observations(detections, joint_idx, joint_conf):
    obs = []
    confs = {}
    for cam_id, detection in detections.items():
        if detection is None:
            continue
        if joint_idx >= len(detection["conf"]):
            continue
        conf = float(detection["conf"][joint_idx])
        if conf < joint_conf:
            continue
        obs.append((cam_id, detection["xy"][joint_idx].astype(np.float64)))
        confs[cam_id] = conf
    return obs, confs


def predict_joint(prev, prev_prev, name):
    if prev and name in prev:
        p = np.asarray(prev[name]["world_m"], dtype=np.float64)
        if prev_prev and name in prev_prev:
            pp = np.asarray(prev_prev[name]["world_m"], dtype=np.float64)
            return p + (p - pp)
        return p
    return None


def candidate_from_pair(obs, cameras, i, j):
    return triangulate_dlt([obs[i], obs[j]], cameras)


def robust_temporal_triangulate_joint(
    obs,
    confs,
    cameras,
    predicted,
    min_views,
    reproj_threshold,
    max_mean_error,
    prediction_gate,
    prediction_weight,
):
    if len(obs) < 2:
        return None
    best = None
    for i in range(len(obs)):
        for j in range(i + 1, len(obs)):
            point = candidate_from_pair(obs, cameras, i, j)
            if point is None or not np.all(np.isfinite(point)):
                continue
            if predicted is not None:
                pred_dist = float(np.linalg.norm(point - predicted))
                if pred_dist > prediction_gate * 3.0:
                    continue
            errors = reprojection_errors(point, obs, cameras)
            inliers = np.where(errors <= reproj_threshold)[0]
            if len(inliers) < min(2, min_views):
                continue
            inlier_obs = [obs[int(idx)] for idx in inliers]
            refined = triangulate_dlt(inlier_obs, cameras)
            if refined is None or not np.all(np.isfinite(refined)):
                continue
            refined_errors = reprojection_errors(refined, inlier_obs, cameras)
            mean_error = float(np.mean(refined_errors))
            if mean_error > max_mean_error:
                continue
            pred_penalty = 0.0
            pred_dist = 0.0
            if predicted is not None:
                pred_dist = float(np.linalg.norm(refined - predicted))
                if pred_dist > prediction_gate and len(inliers) < max(min_views, 4):
                    continue
                pred_penalty = pred_dist * prediction_weight
            confidence = float(np.mean([confs.get(cam_id, 0.0) for cam_id, _ in inlier_obs]))
            score = (
                len(inliers),
                -mean_error,
                -pred_penalty,
                confidence,
            )
            if best is None or score > best["score"]:
                best = {
                    "score": score,
                    "point": refined,
                    "observations": inlier_obs,
                    "errors": refined_errors,
                    "mean_error": mean_error,
                    "max_error": float(np.max(refined_errors)),
                    "prediction_distance_m": pred_dist,
                    "confidence": confidence,
                }
    if best is None:
        return None
    return best


def smooth_point(raw, predicted, alpha):
    if predicted is None:
        return raw
    return alpha * raw + (1.0 - alpha) * predicted


def triangulate_temporal_skeleton(detections, cameras, args, prev, prev_prev, hold_counts):
    skeleton = {}
    report_rows = []
    for joint_idx, name in enumerate(COCO17_NAMES):
        obs, confs = detection_observations(detections, joint_idx, args.joint_conf)
        predicted = predict_joint(prev, prev_prev, name)
        result = robust_temporal_triangulate_joint(
            obs,
            confs,
            cameras,
            predicted,
            args.min_views,
            args.ransac_threshold_px,
            args.max_reprojection_error_px,
            args.prediction_gate_m,
            args.prediction_weight,
        )

        status = "ok"
        if result is None:
            if prev and name in prev and hold_counts.get(name, 0) < args.hold_max_frames:
                previous = dict(prev[name])
                previous["held"] = True
                previous["hold_count"] = hold_counts.get(name, 0) + 1
                skeleton[name] = previous
                hold_counts[name] = hold_counts.get(name, 0) + 1
                status = "held"
                point = np.asarray(previous["world_m"], dtype=np.float64)
                report_rows.append(report_row(name, joint_idx, status, previous.get("cameras_used", []), "", point, previous.get("confidence", 0.0), ""))
                continue
            hold_counts[name] = hold_counts.get(name, 0) + 1
            report_rows.append(report_row(name, joint_idx, "failed", [], "", None, "", ""))
            continue

        raw_point = result["point"]
        point = smooth_point(raw_point, predicted, args.smooth_alpha)
        used_cams = [cam_id for cam_id, _ in result["observations"]]
        skeleton[name] = {
            "joint_index": joint_idx,
            "world_m": point.tolist(),
            "raw_world_m": raw_point.tolist(),
            "cameras_used": used_cams,
            "mean_reprojection_error_px": result["mean_error"],
            "max_reprojection_error_px": result["max_error"],
            "prediction_distance_m": result["prediction_distance_m"],
            "confidence": result["confidence"],
            "held": False,
        }
        hold_counts[name] = 0
        report_rows.append(report_row(name, joint_idx, status, used_cams, result["mean_error"], point, result["confidence"], result["prediction_distance_m"]))
    return skeleton, report_rows, hold_counts


def report_row(name, idx, status, cams, mean_error, point, confidence, pred_dist):
    return {
        "joint": name,
        "joint_index": idx,
        "status": status,
        "cameras_used": len(cams),
        "camera_ids": ",".join(str(cam) for cam in cams),
        "mean_reprojection_error_px": mean_error,
        "prediction_distance_m": pred_dist,
        "x_m": "" if point is None else point[0],
        "y_m": "" if point is None else point[1],
        "z_m": "" if point is None else point[2],
        "confidence": confidence,
    }


def draw_and_save_debug(frame_out, images, detections, skeleton, cameras):
    for cam_id, image in images.items():
        overlay = draw_keypoints(image, detections[cam_id], title=f"cam{cam_id:02d} temporal 2D")
        cv2.imwrite(str(frame_out / f"keypoints_2d_cam{cam_id:02d}.png"), overlay)
        reproj = draw_reprojection(image, skeleton, cameras[cam_id])
        cv2.imwrite(str(frame_out / f"reprojected_3d_cam{cam_id:02d}.png"), reproj)


def write_frame_outputs(frame_out, frame, skeleton, rows, cameras, k):
    metadata = {
        "frame": frame,
        "backend": "RTMPose temporal robust triangulation",
        "intrinsics": {"fx": float(k[0, 0]), "fy": float(k[1, 1]), "cx": float(k[0, 2]), "cy": float(k[1, 2])},
        "coordinate_frame": "Unreal world metres",
        "joints": skeleton,
    }
    (frame_out / "skeleton_3d.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    save_skeleton_ply(frame_out / "skeleton_3d.ply", skeleton, 0.015)
    fields = [
        "joint",
        "joint_index",
        "status",
        "cameras_used",
        "camera_ids",
        "mean_reprojection_error_px",
        "prediction_distance_m",
        "x_m",
        "y_m",
        "z_m",
        "confidence",
    ]
    with (frame_out / "report.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    args = parse_args()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["TMP"]).mkdir(parents=True, exist_ok=True)

    cameras, k = load_camera_data(args.cameras, args.fx, args.fy, args.cx, args.cy)
    detector, pose_model = init_rtmpose(args)

    prev_prev = None
    prev = None
    hold_counts = {}
    summary_rows = []
    for frame in parse_frames(args.frame, args.frames):
        frame_out = Path(args.out) / f"frame{frame}"
        frame_out.mkdir(parents=True, exist_ok=True)
        images = {}
        for cam_id in range(1, 9):
            path = image_path(args.data, cam_id, frame)
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                raise FileNotFoundError(path)
            images[cam_id] = image

        detections = detect_all(detector, pose_model, images, args.det_conf, args.nms_thr)
        skeleton, rows, hold_counts = triangulate_temporal_skeleton(detections, cameras, args, prev, prev_prev, hold_counts)
        if str_to_bool(args.save_debug_images):
            draw_and_save_debug(frame_out, images, detections, skeleton, cameras)
        write_frame_outputs(frame_out, frame, skeleton, rows, cameras, k)

        ok = sum(1 for row in rows if row["status"] == "ok")
        held = sum(1 for row in rows if row["status"] == "held")
        failed = sum(1 for row in rows if row["status"] == "failed")
        detected_cams = sum(1 for detection in detections.values() if detection is not None)
        mean_errs = [float(row["mean_reprojection_error_px"]) for row in rows if row["mean_reprojection_error_px"] != ""]
        mean_err = float(np.mean(mean_errs)) if mean_errs else float("nan")
        print(f"frame {frame}: detected={detected_cams}/8 ok={ok} held={held} failed={failed} mean_err={mean_err:.2f}px")
        summary_rows.append({"frame": frame, "detected_cams": detected_cams, "ok": ok, "held": held, "failed": failed, "mean_error_px": mean_err})
        prev_prev = prev
        prev = skeleton

    with (Path(args.out) / "temporal_summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["frame", "detected_cams", "ok", "held", "failed", "mean_error_px"])
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"wrote: {Path(args.out).resolve()}")


if __name__ == "__main__":
    main()
