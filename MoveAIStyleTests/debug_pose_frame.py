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

from multiview_mono_pose import COCO17_EDGES, COCO17_NAMES, image_path, load_camera_data, project_point
from rtmpose_multiview_mocap import detect_all, init_rtmpose


def parse_args():
    parser = argparse.ArgumentParser(description="Draw 2D RTMPose and 3D dummy reprojection on each camera image")
    parser.add_argument("--data", default="StereoMaskFusion/data")
    parser.add_argument("--frame", default="0068")
    parser.add_argument("--skeleton", default="outputs/moveai_style_rtmpose_anim_100f/frame0068/skeleton_3d.json")
    parser.add_argument("--out", default="outputs/moveai_style_rtmpose_anim_100f/frame0068_debug")
    parser.add_argument("--cameras", default="StereoMaskFusion/data/octopi_cameras_named.json")
    parser.add_argument("--device", default="cuda:0")
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
    parser.add_argument("--nms-thr", type=float, default=0.30)
    parser.add_argument("--bad-error-px", type=float, default=25.0)
    return parser.parse_args()


def load_skeleton(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    joints = {}
    for name, item in data["joints"].items():
        joints[name] = np.asarray(item["world_m"], dtype=np.float64)
    return joints


def draw_pose_lines(image, points, conf=None, color=(0, 255, 0), radius=4, thickness=2, min_conf=0.05):
    canvas = image
    for a, b in COCO17_EDGES:
        if a not in points or b not in points:
            continue
        if conf is not None and (conf.get(a, 0.0) < min_conf or conf.get(b, 0.0) < min_conf):
            continue
        pa = tuple(np.round(points[a]).astype(int))
        pb = tuple(np.round(points[b]).astype(int))
        cv2.line(canvas, pa, pb, color, thickness, cv2.LINE_AA)
    for idx, point in points.items():
        if conf is not None and conf.get(idx, 0.0) < min_conf:
            continue
        p = tuple(np.round(point).astype(int))
        cv2.circle(canvas, p, radius, color, -1, cv2.LINE_AA)
        cv2.putText(canvas, str(idx), (p[0] + 5, p[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
    return canvas


def detection_points(detection):
    if detection is None:
        return {}, {}
    points = {idx: detection["xy"][idx] for idx in range(min(len(detection["xy"]), len(COCO17_NAMES)))}
    conf = {idx: float(detection["conf"][idx]) for idx in range(min(len(detection["conf"]), len(COCO17_NAMES)))}
    return points, conf


def projected_points(skeleton, camera):
    points = {}
    for name, point in skeleton.items():
        if name not in COCO17_NAMES:
            continue
        uv = project_point(point, camera)
        if uv is not None and np.all(np.isfinite(uv)):
            points[COCO17_NAMES.index(name)] = uv
    return points


def draw_error_links(canvas, detected, projected, conf, bad_error_px):
    rows = []
    for idx, uv2d in detected.items():
        if idx not in projected:
            continue
        if conf.get(idx, 0.0) < 0.05:
            continue
        uv3d = projected[idx]
        error = float(np.linalg.norm(uv2d - uv3d))
        color = (0, 255, 255) if error <= bad_error_px else (0, 0, 255)
        p2 = tuple(np.round(uv2d).astype(int))
        p3 = tuple(np.round(uv3d).astype(int))
        cv2.line(canvas, p2, p3, color, 1, cv2.LINE_AA)
        if error > bad_error_px:
            mid = ((p2[0] + p3[0]) // 2, (p2[1] + p3[1]) // 2)
            cv2.putText(canvas, f"{idx}:{error:.0f}", mid, cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
        rows.append((idx, COCO17_NAMES[idx], error, conf.get(idx, 0.0)))
    return rows


def write_contact_sheet(paths, out_path):
    images = [cv2.imread(str(path), cv2.IMREAD_COLOR) for path in paths]
    images = [img for img in images if img is not None]
    if not images:
        return
    thumb_w = 480
    thumbs = []
    for image in images:
        scale = thumb_w / image.shape[1]
        thumbs.append(cv2.resize(image, (thumb_w, int(image.shape[0] * scale)), interpolation=cv2.INTER_AREA))
    rows = []
    for idx in range(0, len(thumbs), 2):
        row = thumbs[idx:idx + 2]
        if len(row) == 1:
            row.append(np.zeros_like(row[0]))
        rows.append(np.hstack(row))
    cv2.imwrite(str(out_path), np.vstack(rows))


def main():
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cameras, _ = load_camera_data(args.cameras, None, None, None, None)
    skeleton = load_skeleton(args.skeleton)

    images = {}
    for cam_id in range(1, 9):
        path = image_path(args.data, cam_id, args.frame)
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(path)
        images[cam_id] = image

    detector, pose_model = init_rtmpose(args)
    detections = detect_all(detector, pose_model, images, args.det_conf, args.nms_thr)

    report_rows = []
    overlay_paths = []
    for cam_id, image in images.items():
        canvas = image.copy()
        detected, conf = detection_points(detections[cam_id])
        projected = projected_points(skeleton, cameras[cam_id])

        draw_pose_lines(canvas, detected, conf=conf, color=(0, 220, 0), radius=4, thickness=2, min_conf=0.05)
        draw_pose_lines(canvas, projected, conf=None, color=(255, 0, 255), radius=3, thickness=2)
        rows = draw_error_links(canvas, detected, projected, conf, args.bad_error_px)

        errors = [row[2] for row in rows]
        mean_error = float(np.mean(errors)) if errors else float("nan")
        max_error = float(np.max(errors)) if errors else float("nan")
        worst = sorted(rows, key=lambda row: row[2], reverse=True)[:5]
        cv2.putText(canvas, f"cam{cam_id:02d} green=2D RTMPose magenta=3D dummy", (24, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, f"mean error {mean_error:.1f}px  max {max_error:.1f}px", (24, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 255, 255), 2, cv2.LINE_AA)

        path = out / f"cam{cam_id:02d}_2d_vs_3d_dummy.png"
        cv2.imwrite(str(path), canvas)
        overlay_paths.append(path)

        for idx, name, error, confidence in rows:
            report_rows.append(
                {
                    "cam": cam_id,
                    "joint_index": idx,
                    "joint": name,
                    "error_px": error,
                    "confidence": confidence,
                    "is_bad": int(error > args.bad_error_px),
                }
            )
        print(f"cam{cam_id:02d}: mean={mean_error:.1f}px max={max_error:.1f}px worst={[(w[1], round(w[2], 1)) for w in worst]}")

    with (out / "per_camera_joint_errors.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["cam", "joint_index", "joint", "error_px", "confidence", "is_bad"])
        writer.writeheader()
        writer.writerows(report_rows)

    write_contact_sheet(overlay_paths, out / "contact_sheet_2d_vs_3d_dummy.png")
    print(f"wrote: {out}")


if __name__ == "__main__":
    main()
