import argparse
import csv
from pathlib import Path

import cv2

from rtmpose_multiview_mocap import detect_one, init_rtmpose


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


def parse_args():
    parser = argparse.ArgumentParser(description="Export RTMPose 2D joints for one camera/frame as CSV.")
    parser.add_argument("--data", default="StereoMaskFusion/data")
    parser.add_argument("--frame", default="0030")
    parser.add_argument("--cam", type=int, default=1)
    parser.add_argument("--out", default="outputs/investor_frame0030_presentations")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--det-config", default="")
    parser.add_argument(
        "--det-checkpoint",
        default=(
            "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/"
            "rtmdet_m_8xb32-100e_coco-obj365-person-235e8209.pth"
        ),
    )
    parser.add_argument("--pose-config", default="")
    parser.add_argument(
        "--pose-checkpoint",
        default=(
            "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/"
            "rtmpose-m_simcc-coco_pt-aic-coco_420e-256x192-d8dd5ca4_20230127.pth"
        ),
    )
    parser.add_argument("--det-conf", type=float, default=0.15)
    parser.add_argument("--nms-thr", type=float, default=0.30)
    parser.add_argument("--usable-threshold", type=float, default=0.20)
    return parser.parse_args()


def image_path(data_root, cam_id, frame):
    return Path(data_root) / f"Cam{cam_id}_Frames" / f"Cam{cam_id}.{frame}.png"


def main():
    args = parse_args()
    path = image_path(args.data, args.cam, args.frame)
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)

    detector, pose_model = init_rtmpose(args)
    detection = detect_one(detector, pose_model, image, args.det_conf, args.nms_thr)
    if detection is None:
        raise RuntimeError(f"No RTMPose person detected for Cam{args.cam} frame {args.frame}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"cam{args.cam:02d}_frame{args.frame}_rtmpose_2d_joints.csv"

    width = int(image.shape[1])
    height = int(image.shape[0])
    rows = []
    for idx, name in enumerate(COCO17_NAMES):
        x = float(detection["xy"][idx][0])
        y = float(detection["xy"][idx][1])
        confidence = float(detection["conf"][idx])
        rows.append(
            {
                "frame": args.frame,
                "camera": f"Cam{args.cam}",
                "joint_index": idx,
                "joint_name": name,
                "x_px": f"{x:.3f}",
                "y_px": f"{y:.3f}",
                "x_norm": f"{x / width:.6f}",
                "y_norm": f"{y / height:.6f}",
                "confidence_0_to_1": f"{confidence:.6f}",
                "usable": "true" if confidence >= args.usable_threshold else "false",
                "person_confidence_0_to_1": f"{float(detection.get('person_conf', 0.0)):.6f}",
                "image_width": width,
                "image_height": height,
            }
        )

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote: {out_path.resolve()}")


if __name__ == "__main__":
    main()
