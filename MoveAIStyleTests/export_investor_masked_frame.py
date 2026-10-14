import argparse
from pathlib import Path

import cv2
import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(description="Export masked investor stills for one multi-view frame.")
    parser.add_argument("--data", default="StereoMaskFusion/data")
    parser.add_argument("--rtmpose-out", default="outputs/investor_frame0030_rtmpose")
    parser.add_argument("--frame", default="0030")
    parser.add_argument("--out", default="outputs/investor_frame0030_presentations")
    parser.add_argument("--cams", default="1,2,3,4,5,6,7,8")
    parser.add_argument("--overlay-dilate", type=int, default=5)
    return parser.parse_args()


def read_image(path, flags=cv2.IMREAD_COLOR):
    image = cv2.imread(str(path), flags)
    if image is None:
        raise FileNotFoundError(path)
    return image


def frame_path(data_root, cam_id, frame):
    return Path(data_root) / f"Cam{cam_id}_Frames" / f"Cam{cam_id}.{frame}.png"


def mask_path(data_root, cam_id, frame):
    return Path(data_root) / "masks" / f"Cam{cam_id}" / f"Cam{cam_id}.{frame}_mask.png"


def overlay_path(rtmpose_root, cam_id, frame):
    return Path(rtmpose_root) / f"frame{frame}" / f"keypoints_2d_cam{cam_id:02d}.png"


def clean_mask(mask):
    mask = (mask > 0).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return mask


def apply_mask(image, mask):
    return cv2.bitwise_and(image, image, mask=mask)


def masked_pose_overlay(frame, mask, overlay, dilate_px):
    masked = apply_mask(frame, mask)
    diff = cv2.cvtColor(cv2.absdiff(frame, overlay), cv2.COLOR_BGR2GRAY)
    pose_layer = diff > 18

    # Drop title text from the RTMPose debug image; keep the pose marks.
    pose_layer[:80, :] = False

    if dilate_px > 0:
        kernel_size = max(1, int(dilate_px) * 2 + 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        valid = cv2.dilate(mask, kernel, iterations=1) > 0
        pose_layer &= valid
    else:
        pose_layer &= mask > 0

    result = masked.copy()
    result[pose_layer] = overlay[pose_layer]
    return result


def make_contact_sheet(paths, out_path, label_prefix):
    images = [read_image(path) for path in paths]
    thumb_w = 480
    thumb_h = 270
    thumbs = []
    for idx, image in enumerate(images, start=1):
        thumb = cv2.resize(image, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        cv2.putText(
            thumb,
            f"{label_prefix} Cam{idx}",
            (16, 34),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.85,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        thumbs.append(thumb)
    rows = [np.hstack(thumbs[0:4]), np.hstack(thumbs[4:8])]
    sheet = np.vstack(rows)
    cv2.imwrite(str(out_path), sheet)


def main():
    args = parse_args()
    out = Path(args.out)
    masked_dir = out / "masked_frames"
    overlay_dir = out / "masked_rtmpose_overlays"
    masked_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)

    cams = [int(part) for part in args.cams.split(",") if part.strip()]
    masked_paths = []
    overlay_paths = []

    for cam_id in cams:
        frame = read_image(frame_path(args.data, cam_id, args.frame))
        mask = clean_mask(read_image(mask_path(args.data, cam_id, args.frame), cv2.IMREAD_GRAYSCALE))
        overlay = read_image(overlay_path(args.rtmpose_out, cam_id, args.frame))

        masked = apply_mask(frame, mask)
        posed = masked_pose_overlay(frame, mask, overlay, args.overlay_dilate)

        masked_out = masked_dir / f"cam{cam_id:02d}_frame{args.frame}_masked.png"
        posed_out = overlay_dir / f"cam{cam_id:02d}_frame{args.frame}_masked_rtmpose.png"
        cv2.imwrite(str(masked_out), masked)
        cv2.imwrite(str(posed_out), posed)
        masked_paths.append(masked_out)
        overlay_paths.append(posed_out)
        print(f"cam{cam_id:02d}: wrote {masked_out} and {posed_out}")

    make_contact_sheet(masked_paths, out / f"frame{args.frame}_masked_contact_sheet.png", "Masked")
    make_contact_sheet(overlay_paths, out / f"frame{args.frame}_masked_rtmpose_contact_sheet.png", "RTMPose")
    print(f"wrote: {out.resolve()}")


if __name__ == "__main__":
    main()
