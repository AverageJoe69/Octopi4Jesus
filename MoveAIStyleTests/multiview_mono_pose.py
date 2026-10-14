import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d


CV_CAMERA_TO_UNREAL_CAMERA = np.array(
    [
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
        [0.0, -1.0, 0.0],
    ],
    dtype=np.float64,
)

COCO17_NAMES = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]

COCO17_EDGES = [
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (0, 1),
    (0, 2),
    (1, 3),
    (2, 4),
]


def parse_args():
    parser = argparse.ArgumentParser(description="Move.ai-style 8-view mono pose triangulation test")
    parser.add_argument("--data", default="StereoMaskFusion/data")
    parser.add_argument("--frame", default="0000")
    parser.add_argument("--out", default="outputs/moveai_style_test/frame0000")
    parser.add_argument("--cameras", default="StereoMaskFusion/data/octopi_cameras_named.json")
    parser.add_argument("--pose-backend", default="yolo", choices=["yolo"])
    parser.add_argument("--pose-model", default="yolo11n-pose.pt")
    parser.add_argument("--fx", type=float, default=None)
    parser.add_argument("--fy", type=float, default=None)
    parser.add_argument("--cx", type=float, default=None)
    parser.add_argument("--cy", type=float, default=None)
    parser.add_argument("--det-conf", type=float, default=0.15)
    parser.add_argument("--joint-conf", type=float, default=0.20)
    parser.add_argument("--min-views", type=int, default=2)
    parser.add_argument("--ransac-threshold-px", type=float, default=20.0)
    parser.add_argument("--ransac-iters", type=int, default=128)
    parser.add_argument("--max-reprojection-error-px", type=float, default=40.0)
    parser.add_argument("--ply-bone-radius", type=float, default=0.015)
    return parser.parse_args()


def rotation_x(degrees):
    a = np.deg2rad(float(degrees))
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def rotation_y_unreal_pitch(degrees):
    a = np.deg2rad(float(degrees))
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, -s], [0, 1, 0], [s, 0, c]], dtype=np.float64)


def rotation_z_unreal_yaw(degrees):
    a = np.deg2rad(float(degrees))
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


def unreal_rotator_to_matrix(rotation):
    return (
        rotation_z_unreal_yaw(rotation.get("yaw", 0.0))
        @ rotation_y_unreal_pitch(rotation.get("pitch", 0.0))
        @ rotation_x(rotation.get("roll", 0.0))
    )


def location_m(camera):
    if "location_unreal_m" in camera:
        return np.asarray(camera["location_unreal_m"], dtype=np.float64)
    if "location_unreal_meters" in camera:
        return np.asarray(camera["location_unreal_meters"], dtype=np.float64)
    if "location_unreal_cm" in camera:
        return np.asarray(camera["location_unreal_cm"], dtype=np.float64) / 100.0
    return np.asarray(camera["location_unreal"], dtype=np.float64)


def camera_to_world(camera):
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = unreal_rotator_to_matrix(camera["rotation_unreal_degrees"]) @ CV_CAMERA_TO_UNREAL_CAMERA
    transform[:3, 3] = location_m(camera)
    return transform


def load_camera_data(path, fx, fy, cx, cy):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    intr = data.get("intrinsics", {})
    k = np.array(
        [
            [float(fx if fx is not None else intr.get("fx", 782.222)), 0.0, float(cx if cx is not None else intr.get("cx", 960.0))],
            [0.0, float(fy if fy is not None else intr.get("fy", 792.0)), float(cy if cy is not None else intr.get("cy", 540.0))],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    cameras = {}
    for camera in data["cameras"]:
        name = str(camera["name"]).lower()
        if "_l" in name:
            continue
        suffix = name.replace("cam", "")
        if suffix.isdigit():
            cam_id = int(suffix)
            t_cw = camera_to_world(camera)
            t_wc = np.linalg.inv(t_cw)
            projection = k @ t_wc[:3, :]
            cameras[cam_id] = {
                "camera_to_world": t_cw,
                "world_to_camera": t_wc,
                "projection": projection,
                "k": k,
            }
    missing = [cam for cam in range(1, 9) if cam not in cameras]
    if missing:
        raise ValueError(f"Missing non-L camera transforms: {missing}")
    return cameras, k


def image_path(data_root, cam_id, frame):
    return Path(data_root) / f"Cam{cam_id}_Frames" / f"Cam{cam_id}.{frame}.png"


def load_yolo_model(model_path):
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Ultralytics is not installed. Install it with: python -m pip install ultralytics"
        ) from exc
    return YOLO(model_path)


def select_best_person(result):
    if result.keypoints is None or result.keypoints.xy is None or len(result.keypoints.xy) == 0:
        return None
    xy = result.keypoints.xy.cpu().numpy()
    conf = result.keypoints.conf.cpu().numpy() if result.keypoints.conf is not None else np.ones(xy.shape[:2])
    boxes_conf = result.boxes.conf.cpu().numpy() if result.boxes is not None and result.boxes.conf is not None else np.ones(len(xy))
    scores = []
    for person_idx in range(len(xy)):
        valid = conf[person_idx] > 0.05
        if not np.any(valid):
            scores.append(-1.0)
            continue
        span = xy[person_idx, valid]
        area = max(1.0, (span[:, 0].max() - span[:, 0].min()) * (span[:, 1].max() - span[:, 1].min()))
        scores.append(float(boxes_conf[person_idx]) * float(np.mean(conf[person_idx, valid])) * area)
    best = int(np.argmax(scores))
    if scores[best] <= 0:
        return None
    return {"xy": xy[best].astype(np.float64), "conf": conf[best].astype(np.float64), "person_conf": float(boxes_conf[best])}


def draw_keypoints(image, detection, title=None):
    canvas = image.copy()
    if detection is not None:
        xy = detection["xy"]
        conf = detection["conf"]
        for a, b in COCO17_EDGES:
            if conf[a] > 0.05 and conf[b] > 0.05:
                pa = tuple(np.round(xy[a]).astype(int))
                pb = tuple(np.round(xy[b]).astype(int))
                cv2.line(canvas, pa, pb, (0, 210, 255), 2, cv2.LINE_AA)
        for idx, point in enumerate(xy):
            if conf[idx] <= 0.05:
                continue
            p = tuple(np.round(point).astype(int))
            cv2.circle(canvas, p, 4, (0, 255, 0), -1, cv2.LINE_AA)
            cv2.putText(canvas, str(idx), (p[0] + 4, p[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1, cv2.LINE_AA)
    if title:
        cv2.putText(canvas, title, (24, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
    return canvas


def detect_all_yolo(model, images, conf):
    detections = {}
    for cam_id, image in images.items():
        results = model.predict(image, conf=conf, verbose=False)
        detections[cam_id] = select_best_person(results[0])
    return detections


def triangulate_dlt(observations, cameras):
    a_rows = []
    for cam_id, uv in observations:
        p = cameras[cam_id]["projection"]
        u, v = float(uv[0]), float(uv[1])
        a_rows.append(u * p[2, :] - p[0, :])
        a_rows.append(v * p[2, :] - p[1, :])
    a = np.asarray(a_rows, dtype=np.float64)
    _, _, vh = np.linalg.svd(a)
    x = vh[-1, :]
    if abs(x[3]) < 1e-12:
        return None
    return x[:3] / x[3]


def project_point(point_world, camera):
    x = np.append(np.asarray(point_world, dtype=np.float64), 1.0)
    point_cam = camera["world_to_camera"] @ x
    if point_cam[2] <= 1e-8:
        return None
    uvw = camera["k"] @ point_cam[:3]
    return uvw[:2] / uvw[2]


def reprojection_errors(point_world, observations, cameras):
    errors = []
    for cam_id, uv in observations:
        projected = project_point(point_world, cameras[cam_id])
        if projected is None:
            errors.append(float("inf"))
        else:
            errors.append(float(np.linalg.norm(projected - uv)))
    return np.asarray(errors, dtype=np.float64)


def triangulate_joint_ransac(observations, cameras, threshold_px, iters, min_views):
    if len(observations) < min_views:
        return None
    rng = np.random.default_rng(12345)
    best = None
    obs = list(observations)
    pair_indices = [(i, j) for i in range(len(obs)) for j in range(i + 1, len(obs))]
    if not pair_indices:
        return None
    for _ in range(max(1, iters)):
        i, j = pair_indices[int(rng.integers(0, len(pair_indices)))]
        candidate = triangulate_dlt([obs[i], obs[j]], cameras)
        if candidate is None or not np.all(np.isfinite(candidate)):
            continue
        errors = reprojection_errors(candidate, obs, cameras)
        inliers = np.where(errors <= threshold_px)[0]
        if len(inliers) < min_views:
            continue
        score = (len(inliers), -float(np.mean(errors[inliers])))
        if best is None or score > best["score"]:
            best = {"score": score, "inliers": inliers}
    if best is None:
        return None
    inlier_obs = [obs[int(i)] for i in best["inliers"]]
    refined = triangulate_dlt(inlier_obs, cameras)
    if refined is None:
        return None
    errors = reprojection_errors(refined, inlier_obs, cameras)
    return {
        "point": refined,
        "observations": inlier_obs,
        "errors": errors,
        "mean_error": float(np.mean(errors)),
        "max_error": float(np.max(errors)),
    }


def triangulate_skeleton(detections, cameras, joint_conf, min_views, threshold_px, iters, max_error):
    skeleton = {}
    report_rows = []
    for joint_idx, name in enumerate(COCO17_NAMES):
        observations = []
        confidences = []
        for cam_id, detection in detections.items():
            if detection is None:
                continue
            if joint_idx >= len(detection["conf"]) or detection["conf"][joint_idx] < joint_conf:
                continue
            observations.append((cam_id, detection["xy"][joint_idx]))
            confidences.append(float(detection["conf"][joint_idx]))
        result = triangulate_joint_ransac(observations, cameras, threshold_px, iters, min_views)
        if result is None or result["mean_error"] > max_error:
            report_rows.append(
                {
                    "joint": name,
                    "joint_index": joint_idx,
                    "status": "failed",
                    "cameras_used": 0 if result is None else len(result["observations"]),
                    "mean_reprojection_error_px": "" if result is None else result["mean_error"],
                    "x_m": "",
                    "y_m": "",
                    "z_m": "",
                    "confidence": "",
                }
            )
            continue
        used_cams = [cam_id for cam_id, _ in result["observations"]]
        used_conf = []
        for cam_id, detection in detections.items():
            if cam_id in used_cams and detection is not None:
                used_conf.append(float(detection["conf"][joint_idx]))
        confidence = float(np.mean(used_conf)) if used_conf else 0.0
        point = result["point"]
        skeleton[name] = {
            "joint_index": joint_idx,
            "world_m": point.tolist(),
            "cameras_used": used_cams,
            "mean_reprojection_error_px": result["mean_error"],
            "max_reprojection_error_px": result["max_error"],
            "confidence": confidence,
        }
        report_rows.append(
            {
                "joint": name,
                "joint_index": joint_idx,
                "status": "ok",
                "cameras_used": len(used_cams),
                "mean_reprojection_error_px": result["mean_error"],
                "x_m": point[0],
                "y_m": point[1],
                "z_m": point[2],
                "confidence": confidence,
            }
        )
    return skeleton, report_rows


def draw_reprojection(image, skeleton, camera):
    canvas = image.copy()
    projected = {}
    for name, joint in skeleton.items():
        uv = project_point(joint["world_m"], camera)
        if uv is None:
            continue
        projected[joint["joint_index"]] = uv
    for a, b in COCO17_EDGES:
        if a in projected and b in projected:
            pa = tuple(np.round(projected[a]).astype(int))
            pb = tuple(np.round(projected[b]).astype(int))
            cv2.line(canvas, pa, pb, (255, 0, 255), 2, cv2.LINE_AA)
    for joint_idx, uv in projected.items():
        p = tuple(np.round(uv).astype(int))
        cv2.circle(canvas, p, 5, (0, 0, 255), -1, cv2.LINE_AA)
        cv2.putText(canvas, str(joint_idx), (p[0] + 4, p[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1, cv2.LINE_AA)
    return canvas


def save_skeleton_ply(path, skeleton, bone_radius):
    points = []
    colors = []
    for name in COCO17_NAMES:
        if name in skeleton:
            points.append(skeleton[name]["world_m"])
            colors.append([1.0, 0.35, 0.02])
    for a, b in COCO17_EDGES:
        name_a = COCO17_NAMES[a]
        name_b = COCO17_NAMES[b]
        if name_a not in skeleton or name_b not in skeleton:
            continue
        pa = np.asarray(skeleton[name_a]["world_m"], dtype=np.float64)
        pb = np.asarray(skeleton[name_b]["world_m"], dtype=np.float64)
        vec = pb - pa
        length = float(np.linalg.norm(vec))
        if length <= 1e-6:
            continue
        steps = max(2, int(length / max(0.005, bone_radius)))
        for t in np.linspace(0.0, 1.0, steps):
            points.append(((1.0 - t) * pa + t * pb).tolist())
            colors.append([0.95, 0.65, 0.05])
    pcd = o3d.geometry.PointCloud()
    if points:
        pcd.points = o3d.utility.Vector3dVector(np.asarray(points, dtype=np.float64))
        pcd.colors = o3d.utility.Vector3dVector(np.asarray(colors, dtype=np.float64))
    o3d.io.write_point_cloud(str(path), pcd)


def rotation_from_z(direction):
    z = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    v = np.cross(z, direction)
    c = float(np.dot(z, direction))
    if np.linalg.norm(v) < 1e-8:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]], dtype=np.float64)
    return np.eye(3) + vx + vx @ vx * ((1.0 - c) / (np.linalg.norm(v) ** 2))


def write_report(path, rows):
    fields = [
        "joint",
        "joint_index",
        "status",
        "cameras_used",
        "mean_reprojection_error_px",
        "x_m",
        "y_m",
        "z_m",
        "confidence",
    ]
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cameras, k = load_camera_data(args.cameras, args.fx, args.fy, args.cx, args.cy)

    images = {}
    for cam_id in range(1, 9):
        path = image_path(args.data, cam_id, args.frame)
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"Missing frame for cam{cam_id}: {path}")
        images[cam_id] = image

    if args.pose_backend == "yolo":
        model = load_yolo_model(args.pose_model)
        detections = detect_all_yolo(model, images, args.det_conf)
    else:
        raise ValueError(f"Unsupported pose backend: {args.pose_backend}")

    for cam_id, image in images.items():
        overlay = draw_keypoints(image, detections[cam_id], title=f"cam{cam_id:02d} 2D pose")
        cv2.imwrite(str(out / f"keypoints_2d_cam{cam_id:02d}.png"), overlay)

    skeleton, rows = triangulate_skeleton(
        detections,
        cameras,
        joint_conf=args.joint_conf,
        min_views=args.min_views,
        threshold_px=args.ransac_threshold_px,
        iters=args.ransac_iters,
        max_error=args.max_reprojection_error_px,
    )

    for cam_id, image in images.items():
        reproj = draw_reprojection(image, skeleton, cameras[cam_id])
        cv2.imwrite(str(out / f"reprojected_3d_cam{cam_id:02d}.png"), reproj)

    metadata = {
        "frame": args.frame,
        "intrinsics": {"fx": float(k[0, 0]), "fy": float(k[1, 1]), "cx": float(k[0, 2]), "cy": float(k[1, 2])},
        "coordinate_frame": "Unreal world metres",
        "joints": skeleton,
    }
    (out / "skeleton_3d.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    save_skeleton_ply(out / "skeleton_3d.ply", skeleton, args.ply_bone_radius)
    write_report(out / "report.csv", rows)

    ok = sum(1 for row in rows if row["status"] == "ok")
    print(f"detected cameras: {sum(1 for det in detections.values() if det is not None)}/8")
    print(f"triangulated joints: {ok}/{len(COCO17_NAMES)}")
    for row in rows:
        if row["status"] == "ok":
            print(
                f"{row['joint']}: cams={row['cameras_used']} "
                f"err={float(row['mean_reprojection_error_px']):.2f}px "
                f"xyz=({float(row['x_m']):.3f}, {float(row['y_m']):.3f}, {float(row['z_m']):.3f}) "
                f"conf={float(row['confidence']):.3f}"
            )
        else:
            print(f"{row['joint']}: failed")
    print(f"wrote: {out}")


if __name__ == "__main__":
    main()
