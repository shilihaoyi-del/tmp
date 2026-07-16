import os
import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    RunningMode,
)

LEFT_COLOR = (255, 100, 100)
RIGHT_COLOR = (100, 255, 100)

options = HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=os.path.join(SCRIPT_DIR, "hand_landmarker.task")),
    running_mode=RunningMode.IMAGE,
    num_hands=2,
    min_hand_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)

landmarker = HandLandmarker.create_from_options(options)

# mediapipe hand connections
connections = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: Could not open camera!")
    exit(1)

print("Press 'q' to quit")
print("Tips: Make sure your hand is clearly visible in the camera frame")
frame_count = 0

while cap.isOpened():
    success, frame = cap.read()
    if not success:
        break

    frame = cv2.flip(frame, 1)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect(mp_image)

    display = frame.copy()

    if result.hand_landmarks:
        if frame_count % 30 == 0:
            print(f"Detected {len(result.hand_landmarks)} hand(s)")
        for idx, landmarks in enumerate(result.hand_landmarks):
            handedness = result.handedness[idx][0]
            label = handedness.display_name
            score = handedness.score
            is_left = label == "Left"

            color = LEFT_COLOR if is_left else RIGHT_COLOR
            display_label = f"{label} Hand ({score:.2f})"

            h, w = frame.shape[:2]

            for lm in landmarks:
                x, y = int(lm.x * w), int(lm.y * h)
                cv2.circle(display, (x, y), 3, color, -1)

            for a, b in connections:
                ax, ay = int(landmarks[a].x * w), int(landmarks[a].y * h)
                bx, by = int(landmarks[b].x * w), int(landmarks[b].y * h)
                cv2.line(display, (ax, ay), (bx, by), color, 2)

            wrist_x = int(landmarks[0].x * w)
            wrist_y = int(landmarks[0].y * h)
            cv2.putText(
                display, display_label, (wrist_x - 60, wrist_y - 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2,
            )

    else:
        if frame_count % 30 == 0:
            print("No hands detected - try better lighting or move hand closer to camera")
        h, w = frame.shape[:2]
        cv2.putText(
            display, "No hands detected", (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2,
        )

    frame_count += 1
    cv2.imshow("Hand Recognition - Left (Red) / Right (Green)", display)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
landmarker.close()
