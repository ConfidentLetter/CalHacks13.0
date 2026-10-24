"""ArUco marker count for the Calibrate mode status line ("4/4 markers"). T5-internal; the real
calibration lives in perception_geometry.calibrate. Never raises."""
from typing import Optional

import cv2

EXPECTED_IDS = (0, 1, 2, 3)


def detect_marker_ids(frame_path: str) -> Optional[list[int]]:
    """Ids of ArUco markers (DICT_4X4_50) found in the image, or None if detection is unavailable."""
    try:
        img = cv2.imread(frame_path)
        if img is None:
            return None
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
        _, ids, _ = detector.detectMarkers(img)
        if ids is None:
            return []
        return sorted({int(i) for i in ids.flatten() if int(i) in EXPECTED_IDS})
    except Exception:
        return None
