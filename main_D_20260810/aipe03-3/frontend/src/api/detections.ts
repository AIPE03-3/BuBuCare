import { fetchEventSource } from '@microsoft/fetch-event-source';
import { BASE_URL } from './client';

/**
 * 即時偵測座標訂閱（SSE：GET /streams/detections/stream?token=...）。
 *
 * 「偵測」模式的骨架是**畫在瀏覽器的 canvas 上**，不是燒在影像裡：
 * AI 端只送座標，`SkeletonOverlay` 疊在乾淨的即時畫面上。
 * 2026-07-31 之前是 AI 端畫好框再推第二條串流（MediaMTX 的 cam_out），
 * 那條已移除，改法與代價見 backend/streams/detections.py 的檔頭。
 *
 * 走 `@microsoft/fetch-event-source` 而非原生 `EventSource`，理由與 useEventSocket 相同：
 * 原生的不能自訂 header，也不能控制 openWhenHidden。token 走 query（後端設計）。
 */

/** 畫面裡的一個人。座標全是 0..1 的比例值，不是像素——乘上 canvas 當下的寬高即可。 */
export interface DetectedPerson {
  /** [x1, y1, x2, y2]，0..1 */
  bbox: [number, number, number, number];
  conf: number;
  is_fall: boolean;
  /** ByteTrack 的跨幀身分；沒有追蹤器時為 null */
  track_id: number | null;
  /** COCO 17 點的 [x, y]（0..1）。沒偵測到的關節點是 [0, 0]，畫的時候要跳過 */
  kps: [number, number][] | null;
}

export interface DetectionFrame {
  /** 對應 `Camera.id`。AI 端的 camera_id 字串格式前端刻意不碰 */
  device_id: number;
  camera_id: string;
  persons: DetectedPerson[];
  seq: number | null;
  source_pts_ms?: number | null;
  rtsp_received_at_ms?: number | null;
  decoder_output_at_ms?: number | null;
  inference_start_at_ms?: number | null;
  inference_end_at_ms?: number | null;
  deepstream_frame_at_ms?: number | null;
  ai_sent_at_ms?: number | null;
  backend_received_at_ms?: number | null;
}

export interface SubscribeOptions {
  /** 登入 token（不是串流權杖——後端會擋掉 scope=stream 的票） */
  token: string;
  /** 只收這台鏡頭的座標；不給就全收 */
  deviceId?: number;
  onFrame: (frame: DetectionFrame) => void;
}

/**
 * 開一條偵測座標的長連線，回傳「收掉它」的函式。
 *
 * ⚠ 呼叫端務必在 effect 的 cleanup 呼叫回傳的函式：SPA 不關會讓連線一直累積，
 *   後端的轉播池每條連線都佔一個信箱（理由同 LiveStream 關 RTCPeerConnection 那段）。
 */
export function subscribeDetections({ token, deviceId, onFrame }: SubscribeOptions): () => void {
  const controller = new AbortController();
  const query = new URLSearchParams({ token });
  if (deviceId !== undefined) query.set('device_id', String(deviceId));

  void fetchEventSource(`${BASE_URL}/streams/detections/stream?${query.toString()}`, {
    signal: controller.signal,
    openWhenHidden: true, // 分頁切到背景時保持連線，值班畫面不應斷線
    onmessage: (msg) => {
      if (msg.event !== 'detections') return; // 心跳（: ping）與其他事件一律略過
      try {
        onFrame(JSON.parse(msg.data) as DetectionFrame);
      } catch {
        // 單一幀解析失敗就丟掉這幀。下一幀馬上補上，不值得把整條連線收掉。
      }
    },
    // 連不上時安靜重試（預設行為）。骨架看不到不該在值班畫面上跳錯誤，
    // 影像本身是另一條路（WebRTC），不受這條影響。
    onerror: () => undefined,
  });

  return () => controller.abort();
}
