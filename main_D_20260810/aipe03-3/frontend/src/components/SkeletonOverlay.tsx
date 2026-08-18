import { useEffect, useRef } from 'react';
import { subscribeDetections, type DetectedPerson } from '../api/detections';
import { useAuth } from '../hooks/useAuth';
import { resolveCssVar } from '../utils/cssVar';

/**
 * 把 AI 的人體框與骨架畫在即時影像上（透明 canvas 疊在 <video> 之上）。
 *
 * 這是「偵測」模式的實作。2026-07-31 之前是 AI 端把框燒進畫面、再推第二條串流，
 * 換成瀏覽器疊圖的理由與代價見 backend/streams/detections.py 的檔頭。
 * 附帶好處：切換即時／偵測不必重新協商 WebRTC，影像不會黑一下。
 *
 * ⚠ 座標全是 0..1 的比例值，所以只要乘上 canvas 當下的寬高即可。
 *   不必知道鏡頭的原始解析度，換鏡頭、拉視窗大小都不用改。
 */

// COCO 17 點的骨架連線。索引對照 ai/pose_to_labelstudio_sdk.py 的 KEYPOINT_NAMES，
// 兩邊是同一套順序（YOLO-Pose 的標準輸出），改一邊就要改另一邊。
const SKELETON: readonly [number, number][] = [
  [0, 1], [0, 2], [1, 3], [2, 4],           // 頭部
  [5, 6],                                    // 肩膀
  [5, 7], [7, 9], [6, 8], [8, 10],           // 手臂
  [5, 11], [6, 12], [11, 12],                // 軀幹
  [11, 13], [13, 15], [12, 14], [14, 16],    // 腿部
];

/**
 * 超過這個時間沒收到新座標就把畫面清空。
 * 沒有這道機制的話，人走出畫面或 AI 停掉時，最後一幀的骨架會一直留在螢幕上，
 * 看起來像「那裡站著一個人」——值班畫面上這是會誤導人的殘影。
 */
const STALE_MS = 1200;

interface SkeletonOverlayProps {
  /** 對應 Camera.id；只畫這台鏡頭的座標 */
  deviceId: number;
}

export function SkeletonOverlay({ deviceId }: SkeletonOverlayProps) {
  // token 自己拿，不從 LiveStream 一路傳下來：這層是實作細節，
  // 呼叫端只該說「要疊哪台鏡頭的骨架」。
  const { session } = useAuth();
  const token = session?.token ?? null;

  const canvasRef = useRef<HTMLCanvasElement>(null);
  // 最新一幀與它的到達時間。放 ref 不放 state：每秒十幾次的 setState 會讓整棵子樹
  // 跟著重繪，而這裡要更新的只有 canvas 的像素。
  const personsRef = useRef<DetectedPerson[]>([]);
  const updatedAtRef = useRef(0);
  const lastDiagnosticAtRef = useRef(0);

  // ── 訂閱座標 ──────────────────────────────────────────
  useEffect(() => {
    if (!token) return;
    personsRef.current = [];
    return subscribeDetections({
      token,
      deviceId,
      onFrame: (frame) => {
        const frontendReceivedAtMs = Date.now();
        personsRef.current = frame.persons;
        updatedAtRef.current = Date.now();
        if (frontendReceivedAtMs - lastDiagnosticAtRef.current >= 1000) {
          lastDiagnosticAtRef.current = frontendReceivedAtMs;
          const video = canvasRef.current?.parentElement?.querySelector('video');
          console.info(`[E2E camera ${deviceId}]`, {
            seq: frame.seq,
            sourcePtsMs: frame.source_pts_ms,
            rtspReceivedAtMs: frame.rtsp_received_at_ms,
            decoderOutputAtMs: frame.decoder_output_at_ms,
            inferenceStartAtMs: frame.inference_start_at_ms,
            inferenceEndAtMs: frame.inference_end_at_ms,
            rtspToDecoderMs:
              frame.decoder_output_at_ms != null && frame.rtsp_received_at_ms != null
                ? frame.decoder_output_at_ms - frame.rtsp_received_at_ms
                : null,
            decoderToInferenceMs:
              frame.inference_start_at_ms != null && frame.decoder_output_at_ms != null
                ? frame.inference_start_at_ms - frame.decoder_output_at_ms
                : null,
            inferenceMs:
              frame.inference_end_at_ms != null && frame.inference_start_at_ms != null
                ? frame.inference_end_at_ms - frame.inference_start_at_ms
                : null,
            rtspToFrontendMs:
              frame.rtsp_received_at_ms != null
                ? frontendReceivedAtMs - frame.rtsp_received_at_ms
                : null,
            deepstreamToAiMs:
              frame.ai_sent_at_ms != null && frame.deepstream_frame_at_ms != null
                ? frame.ai_sent_at_ms - frame.deepstream_frame_at_ms
                : null,
            aiToBackendMs:
              frame.backend_received_at_ms != null && frame.ai_sent_at_ms != null
                ? frame.backend_received_at_ms - frame.ai_sent_at_ms
                : null,
            backendToFrontendMs:
              frame.backend_received_at_ms != null
                ? frontendReceivedAtMs - frame.backend_received_at_ms
                : null,
            aiTotalMs:
              frame.deepstream_frame_at_ms != null
                ? frontendReceivedAtMs - frame.deepstream_frame_at_ms
                : null,
            videoCurrentTimeMs: video ? Math.round(video.currentTime * 1000) : null,
          });
        }
      },
    });
  }, [deviceId, token]);

  // ── 繪製迴圈 ──────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    // 顏色一律取自 design tokens（鐵律二：禁止寫死色碼）。
    // 在 effect 內解析一次而不是每幀：getComputedStyle 每次呼叫都會強制 reflow。
    const colorFall = resolveCssVar('--danger');
    const colorNormal = resolveCssVar('--success');
    const colorBone = resolveCssVar('--brand');
    const colorJoint = resolveCssVar('--bg-surface');
    const colorOutline = resolveCssVar('--text-primary');

    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);

      // canvas 的像素尺寸要跟著它被 CSS 撐開的大小走，否則畫出來會糊掉或偏移
      const { clientWidth: w, clientHeight: h } = canvas;
      if (!w || !h) return;
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      ctx.clearRect(0, 0, w, h);

      if (Date.now() - updatedAtRef.current > STALE_MS) personsRef.current = [];

      for (const person of personsRef.current) {
        const [x1, y1, x2, y2] = person.bbox;
        const boxColor = person.is_fall ? colorFall : colorNormal;

        ctx.strokeStyle = boxColor;
        ctx.lineWidth = 2;
        ctx.strokeRect(x1 * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h);

        if (!person.kps) continue;
        const at = (i: number) => person.kps![i];
        // 沒偵測到的關節點是 [0, 0]（不是畫面左上角），連上去會拉出一條穿過整張圖的線
        const missing = (p: [number, number] | undefined) => !p || (p[0] === 0 && p[1] === 0);

        ctx.strokeStyle = colorBone;
        ctx.lineWidth = 2;
        for (const [a, b] of SKELETON) {
          const pa = at(a);
          const pb = at(b);
          if (missing(pa) || missing(pb)) continue;
          ctx.beginPath();
          ctx.moveTo(pa[0] * w, pa[1] * h);
          ctx.lineTo(pb[0] * w, pb[1] * h);
          ctx.stroke();
        }

        ctx.lineWidth = 1;
        for (const point of person.kps) {
          if (missing(point)) continue;
          ctx.beginPath();
          ctx.arc(point[0] * w, point[1] * h, 3, 0, Math.PI * 2);
          ctx.fillStyle = colorJoint;
          ctx.fill();
          // 淺色關節點畫在淺色畫面上會看不見，補一圈深色描邊
          ctx.strokeStyle = colorOutline;
          ctx.stroke();
        }
      }
    };

    draw();
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <canvas
      ref={canvasRef}
      // aria-hidden：畫面上的資訊（誰跌倒了）由事件卡片與警示彈窗負責播報，
      // 這層純視覺輔助，讀給螢幕閱讀器只會變成噪音。
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 h-full w-full"
    />
  );
}

export default SkeletonOverlay;
