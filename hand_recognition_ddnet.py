"""
Hand gesture recognition using MediaPipe + DD-Net.

MediaPipe detects 21 hand landmarks per frame.
DD-Net (pre-trained on SHREC-14) classifies a 32-frame gesture sequence.

Pipeline:
  Camera -> MediaPipe landmarks (21 x 3D) -> pad to 22 joints
  -> 32-frame rolling buffer -> median filter + center normalize
  -> compute geometry features (pairwise distances)
  -> DD-Net inference -> gesture prediction
"""

import os
import sys
import numpy as np
from collections import deque
from scipy.signal import medfilt
from scipy.spatial.distance import cdist

# Suppress TensorFlow oneDNN warnings
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    RunningMode,
)

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras.models import Model
from tensorflow.keras.layers import (
    Input, Conv1D, Dense, Lambda, Reshape, MaxPooling1D, GlobalMaxPool1D,
    Dropout, SpatialDropout1D, BatchNormalization, LeakyReLU, concatenate,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(SCRIPT_DIR, "hand_landmarker.task")
DDNET_WEIGHTS = os.path.join(
    os.path.dirname(SCRIPT_DIR), "DD-Net-master", "DD-Net-master",
    "SHREC", "weights", "coarse_heavy.h5"
)

# ---------------------------------------------------------------------------
# DD-Net config (must match the pre-trained SHREC-14 Heavy model)
# ---------------------------------------------------------------------------
FRAME_L = 32        # temporal frames per gesture
JOINT_N = 22        # SHREC uses 22 joints (we pad MediaPipe's 21 -> 22)
JOINT_D = 3         # x, y, z
FEAT_D = 231        # 22 * 21 / 2  (pairwise distances)
CLC_NUM = 14        # SHREC-14 gesture classes
FILTERS = 64        # "heavy" variant

# Gesture labels (SHREC-14)
GESTURE_NAMES = [
    "Grab",            # 0
    "Tap",             # 1
    "Expand",          # 2
    "Pinch",           # 3
    "Rotation CW",     # 4
    "Rotation CCW",    # 5
    "Swipe Right",     # 6
    "Swipe Left",      # 7
    "Swipe Up",        # 8
    "Swipe Down",      # 9
    "Swipe V",         # 10
    "Swipe Cross",     # 11
    "Shake",           # 12
    "Other",           # 13
]

# ---------------------------------------------------------------------------
# DD-Net model definition (identical to SHREC/train_coarse.py)
# ---------------------------------------------------------------------------

def poses_diff(x):
    H, W = x.get_shape()[1], x.get_shape()[2]
    x = tf.subtract(x[:, 1:, ...], x[:, :-1, ...])
    x = tf.image.resize(x, size=[H, W])
    return x


def pose_motion(P, frame_l):
    P_diff_slow = Lambda(lambda x: poses_diff(x))(P)
    P_diff_slow = Reshape((frame_l, -1))(P_diff_slow)
    P_fast = Lambda(lambda x: x[:, ::2, ...])(P)
    P_diff_fast = Lambda(lambda x: poses_diff(x))(P_fast)
    P_diff_fast = Reshape((int(frame_l / 2), -1))(P_diff_fast)
    return P_diff_slow, P_diff_fast


def c1D(x, filters, kernel):
    x = Conv1D(filters, kernel_size=kernel, padding="same", use_bias=False)(x)
    x = BatchNormalization()(x)
    x = LeakyReLU(alpha=0.2)(x)
    return x


def block(x, filters):
    x = c1D(x, filters, 3)
    x = c1D(x, filters, 3)
    return x


def d1D(x, filters):
    x = Dense(filters, use_bias=False)(x)
    x = BatchNormalization()(x)
    x = LeakyReLU(alpha=0.2)(x)
    return x


def build_FM(frame_l, joint_n, joint_d, feat_d, filters):
    M = Input(shape=(frame_l, feat_d))
    P = Input(shape=(frame_l, joint_n, joint_d))

    diff_slow, diff_fast = pose_motion(P, frame_l)

    x = c1D(M, filters * 2, 1)
    x = SpatialDropout1D(0.1)(x)
    x = c1D(x, filters, 3)
    x = SpatialDropout1D(0.1)(x)
    x = c1D(x, filters, 1)
    x = MaxPooling1D(2)(x)
    x = SpatialDropout1D(0.1)(x)

    x_d_slow = c1D(diff_slow, filters * 2, 1)
    x_d_slow = SpatialDropout1D(0.1)(x_d_slow)
    x_d_slow = c1D(x_d_slow, filters, 3)
    x_d_slow = SpatialDropout1D(0.1)(x_d_slow)
    x_d_slow = c1D(x_d_slow, filters, 1)
    x_d_slow = MaxPooling1D(2)(x_d_slow)
    x_d_slow = SpatialDropout1D(0.1)(x_d_slow)

    x_d_fast = c1D(diff_fast, filters * 2, 1)
    x_d_fast = SpatialDropout1D(0.1)(x_d_fast)
    x_d_fast = c1D(x_d_fast, filters, 3)
    x_d_fast = SpatialDropout1D(0.1)(x_d_fast)
    x_d_fast = c1D(x_d_fast, filters, 1)
    x_d_fast = SpatialDropout1D(0.1)(x_d_fast)

    x = concatenate([x, x_d_slow, x_d_fast])
    x = block(x, filters * 2)
    x = MaxPooling1D(2)(x)
    x = SpatialDropout1D(0.1)(x)

    x = block(x, filters * 4)
    x = MaxPooling1D(2)(x)
    x = SpatialDropout1D(0.1)(x)

    x = block(x, filters * 8)
    x = SpatialDropout1D(0.1)(x)

    return Model(inputs=[M, P], outputs=x)


def build_DD_Net(frame_l, joint_n, joint_d, feat_d, clc_num, filters):
    M = Input(name="M", shape=(frame_l, feat_d))
    P = Input(name="P", shape=(frame_l, joint_n, joint_d))

    FM = build_FM(frame_l, joint_n, joint_d, feat_d, filters)

    x = FM([M, P])
    x = GlobalMaxPool1D()(x)
    x = d1D(x, 128)
    x = Dropout(0.5)(x)
    x = d1D(x, 128)
    x = Dropout(0.5)(x)
    x = Dense(clc_num, activation="softmax")(x)

    return Model(inputs=[M, P], outputs=x)


# ---------------------------------------------------------------------------
# DD-Net preprocessing (adapted from SHREC/utils.py)
# ---------------------------------------------------------------------------

def normlize_range(p):
    """Center joint coordinates by subtracting the per-dimension mean."""
    p[:, :, 0] = p[:, :, 0] - np.mean(p[:, :, 0])
    p[:, :, 1] = p[:, :, 1] - np.mean(p[:, :, 1])
    p[:, :, 2] = p[:, :, 2] - np.mean(p[:, :, 2])
    return p


def get_CG(p, joint_n, frame_l):
    """Compute pairwise Euclidean distances (upper triangle) per frame."""
    iu = np.triu_indices(joint_n, 1, joint_n)
    M = []
    for f in range(frame_l):
        d_m = cdist(p[f], np.concatenate([p[f], np.zeros([1, p.shape[2]])]),
                    "euclidean")
        d_m = d_m[iu]
        M.append(d_m)
    return np.stack(M)


def preprocess_sequence(raw_sequence):
    """
    Preprocess a sequence of MediaPipe landmarks for DD-Net.

    Args:
        raw_sequence: numpy array of shape (32, 21, 3)
    Returns:
        M: geometry features (1, 32, 231)
        P: centered poses (1, 32, 22, 3)
    """
    seq = raw_sequence.copy().astype(np.float32)

    # 1. Apply median filter per joint per axis (as in DD-Net zoom())
    for m in range(21):
        for n in range(3):
            seq[:, m, n] = medfilt(seq[:, m, n], 3)

    # 2. Pad from 21 landmarks to 22 joints (add palm center as 22nd)
    #    Palm center = midpoint between wrist (0) and middle finger MCP (9)
    palm_center = (seq[:, 0, :] + seq[:, 9, :]) / 2.0
    palm_center = palm_center[:, np.newaxis, :]  # (32, 1, 3)
    seq_22 = np.concatenate([seq, palm_center], axis=1)  # (32, 22, 3)

    # 3. Center normalize per dimension
    seq_22 = normlize_range(seq_22)

    # 4. Compute geometry features M
    M = get_CG(seq_22, JOINT_N, FRAME_L)  # (32, 231)

    return M[np.newaxis, ...], seq_22[np.newaxis, ...]


# ---------------------------------------------------------------------------
# MediaPipe setup
# ---------------------------------------------------------------------------

def create_landmarker():
    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=RunningMode.IMAGE,
        num_hands=2,
        min_hand_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return HandLandmarker.create_from_options(options)


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def draw_landmarks(frame, landmarks, w, h, color=(100, 255, 100)):
    connections = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (0, 9), (9, 10), (10, 11), (11, 12),
        (0, 13), (13, 14), (14, 15), (15, 16),
        (0, 17), (17, 18), (18, 19), (19, 20),
        (5, 9), (9, 13), (13, 17),
    ]
    for lm in landmarks:
        x, y = int(lm.x * w), int(lm.y * h)
        cv2.circle(frame, (x, y), 2, color, -1)
    for a, b in connections:
        ax, ay = int(landmarks[a].x * w), int(landmarks[a].y * h)
        bx, by = int(landmarks[b].x * w), int(landmarks[b].y * h)
        cv2.line(frame, (ax, ay), (bx, by), color, 1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 55)
    print("  DD-Net + MediaPipe -> Arm Bridge (HTTP/MQTT)")
    print("=" * 55)

    from pc_arm_bridge import ArmBridge

    # 1. Load DD-Net model
    print("\n[1/5] Building DD-Net (Heavy, SHREC-14)...")
    model = build_DD_Net(FRAME_L, JOINT_N, JOINT_D, FEAT_D, CLC_NUM, FILTERS)

    if os.path.exists(DDNET_WEIGHTS):
        print(f"       Loading weights: {DDNET_WEIGHTS}")
        model.load_weights(DDNET_WEIGHTS)
        print("       Weights loaded successfully.")
    else:
        print(f"       WARNING: weights not found at {DDNET_WEIGHTS}")
        print("       Running with random weights (predictions will be meaningless).")
        print("       Download the pre-trained SHREC model or train your own.")
        dummy_M = np.zeros((1, FRAME_L, FEAT_D), dtype=np.float32)
        dummy_P = np.zeros((1, FRAME_L, JOINT_N, JOINT_D), dtype=np.float32)
        _ = model([dummy_M, dummy_P])

    # 2. Load MediaPipe
    print("[2/5] Loading MediaPipe Hand Landmarker...")
    landmarker = create_landmarker()
    print("       MediaPipe ready.")

    # 3. Open camera
    print("[3/5] Opening camera...")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("       ERROR: Could not open camera!")
        landmarker.close()
        return
    print("       Camera opened.")

    # 4. Arm bridge (gesture -> joints -> backend)
    print("[4/5] Connecting arm bridge...")
    bridge = ArmBridge()
    bridge.start_session()

    # 5. Initialize state
    print("[5/5] Starting recognition loop...")
    print("       Collecting 32 frames before first prediction...")
    print("       Keys: q=quit  s=start  p=pause  e=estop")
    print("       Tip: backend ENABLE_SIMULATOR=false when using this script.\n")

    buffers = {"Left": deque(maxlen=FRAME_L), "Right": deque(maxlen=FRAME_L)}
    gestures = {"Left": "Collecting...", "Right": "Collecting..."}
    confidences = {"Left": 0.0, "Right": 0.0}
    last_publish = "—"
    frame_i = 0

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            break

        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_image)

        display = frame.copy()
        active_hands = set()
        gesture_updated = False

        if result.hand_landmarks:
            for i, landmarks in enumerate(result.hand_landmarks):
                hand_label = result.handedness[i][0].category_name  # "Left" or "Right"

                pts = np.array([[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float32)
                buffers[hand_label].append(pts)
                active_hands.add(hand_label)

                color = (100, 255, 100) if hand_label == "Right" else (255, 150, 50)
                draw_landmarks(display, landmarks, w, h, color)

                wrist = landmarks[0]
                wx, wy = int(wrist.x * w), int(wrist.y * h)
                cv2.putText(display, hand_label, (wx - 20, wy - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                if len(buffers[hand_label]) == FRAME_L:
                    seq = np.stack(list(buffers[hand_label]), axis=0)
                    M, P = preprocess_sequence(seq)
                    preds = model.predict([M, P], verbose=0)[0]
                    top_idx = np.argmax(preds)
                    gestures[hand_label] = GESTURE_NAMES[top_idx]
                    confidences[hand_label] = float(preds[top_idx])
                    gesture_updated = True

                    g_text = f"{gestures[hand_label]} ({confidences[hand_label]:.1%})"
                    cv2.putText(display, g_text, (wx - 30, wy - 35),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        for hand in ("Left", "Right"):
            if hand not in active_hands:
                buffers[hand].clear()
                gestures[hand] = "Collecting..."
                confidences[hand] = 0.0

        # Map + publish when we have a fresh prediction
        if gesture_updated:
            left_ready = len(buffers["Left"]) == FRAME_L
            right_ready = len(buffers["Right"]) == FRAME_L
            mapped = bridge.on_gestures(
                left_g=gestures["Left"] if left_ready else None,
                right_g=gestures["Right"] if right_ready else None,
                left_c=confidences["Left"] if left_ready else 0.0,
                right_c=confidences["Right"] if right_ready else 0.0,
            )
            if mapped and mapped.applied:
                last_publish = f"{mapped.reason} -> {[round(v, 1) for v in mapped.joints]}"
                print(f"[publish #{bridge.seq}] {last_publish}")

        frame_i += 1
        if frame_i % 30 == 0:
            bridge.heartbeat()

        # Sidebar
        y_offset = 30
        for hand in ("Left", "Right"):
            buf_fill = len(buffers[hand])
            color = (255, 150, 50) if hand == "Left" else (100, 255, 100)
            status = f"{hand}: [{buf_fill}/{FRAME_L}]"
            if buf_fill == FRAME_L:
                status += f"  {gestures[hand]} ({confidences[hand]:.1%})"
            cv2.putText(display, status, (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)
            y_offset += 25

        link = f"HTTP={'OK' if bridge.http_ok else '--'} MQTT={'OK' if bridge.mqtt_ok else '--'}"
        cv2.putText(display, link, (10, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        y_offset += 22
        cv2.putText(display, f"PUB: {last_publish[:70]}", (10, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 255, 180), 1)

        cv2.imshow("DD-Net Hand -> Arm Bridge", display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            bridge.start_session()
        if key == ord("p"):
            bridge._http_json("POST", "/api/control", {"action": "pause"})
        if key == ord("e"):
            bridge._http_json("POST", "/api/control", {"action": "estop"})

    cap.release()
    cv2.destroyAllWindows()
    landmarker.close()
    bridge.close()
    print("Done.")


if __name__ == "__main__":
    main()
