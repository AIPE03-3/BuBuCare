import json
import os
import socket
import time
import urllib.request
import urllib.error
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

UDP_HOST = "0.0.0.0"
UDP_PORT = int(os.getenv("UDP_PORT", "19000"))
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "http://backend:8000",
).rstrip("/")
EVENT_API_KEY = os.getenv("EVENT_API_KEY", "")
FALL_CONFIRM_FRAMES = int(os.getenv("FALL_CONFIRM_FRAMES", "3"))
FALL_CLEAR_FRAMES = int(os.getenv("FALL_CLEAR_FRAMES", "10"))
FALL_COOLDOWN_SECONDS = float(os.getenv("FALL_COOLDOWN_SECONDS", "30"))
FALL_MIN_CONFIDENCE = float(os.getenv("FALL_MIN_CONFIDENCE", "0.35"))
FALL_BBOX_RATIO = float(os.getenv("FALL_BBOX_RATIO", "0.60"))
STREAM_FPS = float(os.getenv("STREAM_FPS", "10"))

# 本機循環測試影片。事件建立時把 DeepStream 幀序號換算成影片位置，
# URL fragment 讓瀏覽器從跌倒前三秒開始播放，而不是顯示事後即時畫面。
DEMO_CLIPS = {
    301: ("test7.mp4", 17.6),
    302: ("test8.mp4", 22.3),
    303: ("test5.mp4", 22.85),
    304: ("test6.mp4", 16.509),
}

fall_counts: dict[int, int] = {}
fall_start_pts_ms: dict[int, int] = {}
clear_counts: dict[int, int] = {}
fall_latched: dict[int, bool] = {}
last_fall_event_at: dict[int, float] = {}
pose_history: dict[int, deque] = {}
TAIPEI = ZoneInfo("Asia/Taipei")


def _point(kps: list, index: int):
    if index >= len(kps) or len(kps[index]) < 2:
        return None
    x, y = kps[index][0], kps[index][1]
    if (x == 0 and y == 0) or not (0 <= x <= 1 and 0 <= y <= 1):
        return None
    return float(x), float(y)


def pose_metrics(person: dict):
    if float(person.get("conf") or 0) < FALL_MIN_CONFIDENCE:
        return None

    bbox = person.get("bbox") or []
    horizontal_box = False
    if len(bbox) == 4:
        width = max(0.0, float(bbox[2]) - float(bbox[0]))
        height = max(0.001, float(bbox[3]) - float(bbox[1]))
        horizontal_box = width / height >= FALL_BBOX_RATIO

    kps = person.get("kps") or []
    shoulders = [_point(kps, 5), _point(kps, 6)]
    hips = [_point(kps, 11), _point(kps, 12)]
    ankles = [_point(kps, 15), _point(kps, 16)]
    shoulders = [point for point in shoulders if point]
    hips = [point for point in hips if point]
    ankles = [point for point in ankles if point]
    horizontal_torso = False
    if shoulders and hips:
        shoulder = (
            sum(point[0] for point in shoulders) / len(shoulders),
            sum(point[1] for point in shoulders) / len(shoulders),
        )
        hip = (
            sum(point[0] for point in hips) / len(hips),
            sum(point[1] for point in hips) / len(hips),
        )
        dx = abs(shoulder[0] - hip[0])
        dy = abs(shoulder[1] - hip[1])
        horizontal_torso = dx >= max(0.04, dy * 1.15)

    hip_y = None
    if hips:
        hip_y = sum(point[1] for point in hips) / len(hips)
    body_points = shoulders + hips + ankles
    horizontal_body = False
    if len(body_points) >= 3:
        span_x = max(point[0] for point in body_points) - min(point[0] for point in body_points)
        span_y = max(point[1] for point in body_points) - min(point[1] for point in body_points)
        horizontal_body = span_x >= 0.12 and span_y <= span_x * 0.75
    return {
        "confidence": float(person.get("conf") or 0.0),
        "ratio": width / height if len(bbox) == 4 else 0.0,
        "horizontal_torso": horizontal_torso,
        "horizontal_body": horizontal_body,
        "hip_y": hip_y,
    }


def looks_like_fall(device_id: int, person: dict, now: float) -> bool:
    """Require a standing-to-downward-to-lying transition; a crouch alone is not a fall."""
    metrics = pose_metrics(person)
    if metrics is None:
        return False

    history = pose_history.setdefault(device_id, deque(maxlen=40))
    recent = [item for item in history if now - item[0] <= 2.5]
    was_upright = any(
        item[1] <= 0.55 and not item[2]
        for item in recent
    )
    rapid_hips = [item[3] for item in recent if now - item[0] <= 0.9 and item[3] is not None]
    descended_rapidly = (
        metrics["hip_y"] is not None
        and rapid_hips
        and metrics["hip_y"] - min(rapid_hips) >= 0.10
    )
    # Real test clips often produce a 0.60-0.71 box ratio after impact.  A
    # crouch can have the same box ratio, but its shoulder/hip/ankle keypoints
    # remain vertically stacked.  Prefer the full-body axis; use 0.72 only as
    # fallback when ankles are temporarily missing.
    lying = (
        metrics["horizontal_body"]
        or metrics["horizontal_torso"]
        or metrics["ratio"] >= 0.72
    )
    return lying and was_upright and descended_rapidly


def event_clip_path(device_id: int, source_pts_ms: int) -> str:
    clip = DEMO_CLIPS.get(device_id)
    if clip is None or STREAM_FPS <= 0:
        return ""
    filename, duration = clip
    detected_position = (source_pts_ms / 1000.0) % duration
    start = max(0.0, detected_position - 3.0)
    return f"/event-videos/{filename}#t={start:.1f}"


def post_event(device_id: int, score: float, source_pts_ms: int) -> None:
    body = json.dumps({
        "device_id": device_id,
        "event_type": "fall",
        "clip_path": event_clip_path(device_id, source_pts_ms),
        # detect_events.detected_at is a timezone-naive DB column and the
        # frontend intentionally interprets naive timestamps as UTC+8.
        "detected_at": datetime.now(TAIPEI).replace(tzinfo=None).isoformat(),
        "yolo_score": score,
        "vlm_summary": "姿態模型連續偵測到橫躺姿勢，請值班人員立即確認。",
        "ai_verdict": "true_alarm",
        "ai_confidence": score,
        "ai_reasoning": f"連續 {FALL_CONFIRM_FRAMES} 幀符合跌倒姿態規則。",
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{BACKEND_URL}/events",
        data=body,
        headers={"Content-Type": "application/json", "X-API-Key": EVENT_API_KEY},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2.0) as response:
        response.read()


def post_detection(payload: bytes) -> None:
    request = urllib.request.Request(
        f"{BACKEND_URL}/streams/detections",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": EVENT_API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=0.5) as response:
            response.read()
    except urllib.error.HTTPError as error:
        print(f"HTTP error: {error.code}", flush=True)
    except Exception as error:
        print(f"Detection bridge error: {error}", flush=True)


def main() -> None:
    if not EVENT_API_KEY:
        raise RuntimeError("EVENT_API_KEY 沒有設定")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_HOST, UDP_PORT))

    print(
        f"Detection bridge listening UDP :{UDP_PORT}"
        f" -> {BACKEND_URL}/streams/detections",
        flush=True,
    )

    while True:
        payload, _ = sock.recvfrom(65535)

        # 丟掉已經排隊的舊幀，只保留最新一幀。
        sock.setblocking(False)
        try:
            while True:
                payload, _ = sock.recvfrom(65535)
        except BlockingIOError:
            pass
        finally:
            sock.setblocking(True)

        try:
            frame = json.loads(payload)
        except json.JSONDecodeError:
            print("Dropped invalid JSON", flush=True)
            continue

        device_id = int(frame.get("device_id", 0))
        persons = frame.get("persons") or []
        candidates = []
        frame_now = time.monotonic()
        for person in persons:
            is_fall = looks_like_fall(device_id, person, frame_now)
            person["is_fall"] = is_fall
            if is_fall:
                candidates.append(person)

        seq = int(frame.get("seq") or 0)
        source_pts_ms = int(frame.get("source_pts_ms") or 0)

        # Store the best visible person's current posture after evaluating the
        # transition, so the current frame cannot satisfy its own history.
        visible_metrics = [pose_metrics(person) for person in persons]
        visible_metrics = [metrics for metrics in visible_metrics if metrics]
        if visible_metrics:
            best = max(visible_metrics, key=lambda metrics: metrics["confidence"])
            pose_history.setdefault(device_id, deque(maxlen=40)).append(
                (
                    frame_now,
                    best["ratio"],
                    best["horizontal_torso"] or best["horizontal_body"],
                    best["hip_y"],
                )
            )
        if seq and seq % 50 == 0:
            ratios = []
            for person in persons:
                bbox = person.get("bbox") or []
                if len(bbox) == 4:
                    width = max(0.0, float(bbox[2]) - float(bbox[0]))
                    height = max(0.001, float(bbox[3]) - float(bbox[1]))
                    ratios.append(width / height)
            max_conf = max((float(person.get("conf") or 0) for person in persons), default=0.0)
            print(
                f"Pose stats: device={device_id} seq={seq} persons={len(persons)} "
                f"max_conf={max_conf:.3f} max_bbox_ratio={max(ratios, default=0.0):.3f} "
                f"fall_candidates={len(candidates)}",
                flush=True,
            )

        if candidates:
            if fall_counts.get(device_id, 0) == 0:
                fall_start_pts_ms[device_id] = source_pts_ms
            fall_counts[device_id] = fall_counts.get(device_id, 0) + 1
            clear_counts[device_id] = 0
        else:
            # 遠距攝影機偶爾漏一幀人體；逐步衰減而非立即歸零。
            fall_counts[device_id] = max(0, fall_counts.get(device_id, 0) - 1)
            clear_counts[device_id] = clear_counts.get(device_id, 0) + 1
            if clear_counts[device_id] >= FALL_CLEAR_FRAMES:
                fall_latched[device_id] = False
                fall_start_pts_ms.pop(device_id, None)
        post_detection(json.dumps(frame, separators=(",", ":")).encode("utf-8"))

        now = time.monotonic()
        since_last = now - last_fall_event_at.get(device_id, -FALL_COOLDOWN_SECONDS)
        if (
            fall_counts[device_id] >= FALL_CONFIRM_FRAMES
            and not fall_latched.get(device_id, False)
            and since_last >= FALL_COOLDOWN_SECONDS
        ):
            score = max(float(person.get("conf") or 0) for person in candidates)
            try:
                post_event(device_id, score, fall_start_pts_ms.get(device_id, source_pts_ms))
                last_fall_event_at[device_id] = now
                fall_latched[device_id] = True
                fall_counts[device_id] = 0
                print(f"Fall event created: device={device_id} score={score:.3f}", flush=True)
            except Exception as error:
                print(f"Fall event error: device={device_id}: {error}", flush=True)


if __name__ == "__main__":
    main()
