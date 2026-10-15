"""
摄像头实时表情识别
打开摄像头，实时检测画面中每一张脸的表情，并在画面上标注出来。
按 q 退出。
"""

import cv2
from deepface import DeepFace

# 表情英文 -> 中文对照（画面上用英文标注，cv2.putText 不支持中文）
EMOTION_CN = {
    "angry": "愤怒",
    "disgust": "厌恶",
    "fear": "恐惧",
    "happy": "开心",
    "sad": "伤心",
    "surprise": "惊讶",
    "neutral": "平静",
}

ANALYZE_INTERVAL = 3  # 每 3 帧分析一次，兼顾流畅度和准确度

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    raise SystemExit("无法打开摄像头，请检查摄像头是否被其他程序占用")

print("摄像头已打开。表情对照：", "，".join(f"{k}={v}" for k, v in EMOTION_CN.items()))
print("按 q 退出")

last_faces = []  # 缓存最近一次的分析结果，未分析的帧继续用它画框
frame_idx = 0

while True:
    ret, frame = cap.read()
    if not ret:
        print("读取画面失败")
        break

    # 左右镜像翻转，更符合自拍视角
    frame = cv2.flip(frame, 1)
    frame_idx += 1

    if frame_idx % ANALYZE_INTERVAL == 0:
        try:
            faces = DeepFace.analyze(
                frame,
                actions=["emotion"],
                detector_backend="opencv",  # 最轻量的人脸检测器，适合实时场景
                enforce_detection=False,
                silent=True,
            )
            last_faces = [f for f in faces if f["region"]["w"] > 0]
        except Exception:
            last_faces = []

    for face in last_faces:
        r = face["region"]
        x, y, w, h = r["x"], r["y"], r["w"], r["h"]
        emotion = face["dominant_emotion"]
        score = face["emotion"][emotion]

        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 200, 0), 2)
        cv2.putText(
            frame,
            f"{emotion} {score:.0f}%",
            (x, y - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 200, 0),
            2,
        )
        # 同时打印到控制台（带中文）
        print(f"\r表情: {EMOTION_CN.get(emotion, emotion)}（{emotion}）置信度 {score:.0f}%   ", end="")

    cv2.imshow("Emotion Recognition - press q to quit", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
