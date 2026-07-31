import { useEffect, useRef, useState } from 'react';
import { fetchStreamToken, negotiateWhep } from '../api/streams';
import { CAMERA_LABEL } from '../types';
import { SkeletonOverlay } from './SkeletonOverlay';

type ConnectionState = 'connecting' | 'connected' | 'failed';

interface LiveStreamProps {
  /** 完整 WHEP 網址；null＝這個環境沒有這條串流，顯示占位框 */
  whepUrl: string | null;
  /**
   * 頻道名（cam_in / phone_a…），用來跟後端換串流權杖。
   * ⚠ 必須與 whepUrl 是「同一個模式」的一組——即時就兩個都給即時的，
   *   不可一個給即時、一個給偵測，否則換來的票對不上要看的頻道，MediaMTX 會回 401。
   */
  channel: string | null;
  /** 占位框文字。預設「鏡頭即時影像」；偵測模式下沒有 AI 的鏡頭傳「此鏡頭無 AI 偵測」 */
  emptyLabel?: string;
  /**
   * 給值就在影像上疊 AI 骨架（＝「偵測」模式），值是那台鏡頭的 `Camera.id`。
   * null／不給＝純影像。
   *
   * ⚠ 這個 prop **不影響 WebRTC 連線**（不在下面 effect 的相依陣列裡），
   *   所以切換即時／偵測時影像不會斷、不必重新協商。2026-07-31 之前偵測模式是
   *   換一條串流網址，每次切換都要重連、畫面會黑一下。
   */
  overlayDeviceId?: number | null;
}

/**
 * 等 ICE candidate 收集完再送出 SDP：一次帶齊所有候選路徑，
 * 省掉逐筆傳送的來回協商（MediaMTX 支援這種一次性做法）。
 */
function waitForIceGathering(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const onChange = () => {
      if (pc.iceGatheringState !== 'complete') return;
      pc.removeEventListener('icegatheringstatechange', onChange);
      resolve();
    };
    pc.addEventListener('icegatheringstatechange', onChange);
  });
}

export function LiveStream({
  whepUrl,
  channel,
  emptyLabel = CAMERA_LABEL.LIVE_PLACEHOLDER,
  overlayDeviceId = null,
}: LiveStreamProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<ConnectionState>('connecting');
  // 遞增此值即觸發重新連線（重試按鈕用）
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const video = videoRef.current;
    // channel 與 whepUrl 一定同時有值（都來自同一台鏡頭的同一個模式）；
    // 少了 channel 就換不到權杖，連了也是白連，所以一併擋在這裡
    if (!whepUrl || !channel || !video) return;

    let cancelled = false;
    setState('connecting');

    const pc = new RTCPeerConnection({ iceServers: [] });
    // 這個頁面只收影像、不送影像
    pc.addTransceiver('video', { direction: 'recvonly' });

    pc.ontrack = (event) => {
      video.srcObject = event.streams[0] ?? new MediaStream([event.track]);
      // 自動播放被瀏覽器擋下時不需要報錯，畫面停在第一格即可
      void video.play().catch(() => undefined);
    };

    pc.onconnectionstatechange = () => {
      if (cancelled) return;
      if (pc.connectionState === 'connected') setState('connected');
      if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') setState('failed');
    };

    void (async () => {
      try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await waitForIceGathering(pc);
        // 換票刻意排在 ICE 收集之後：收集要花一兩秒，票只有 60 秒命，越晚換剩得越多。
        // 「重新連線」按鈕會重跑整段 effect，所以每次重試都是一張新票，不會拿到過期的。
        const streamToken = await fetchStreamToken(channel);
        if (cancelled) return;
        const answer = await negotiateWhep(whepUrl, pc.localDescription?.sdp ?? '', streamToken);
        if (cancelled) return;
        await pc.setRemoteDescription({ type: 'answer', sdp: answer });
      } catch {
        if (!cancelled) setState('failed');
      }
    })();

    // 元件收掉或換頻道時務必關閉：SPA 不關會讓連線一直累積、佔用頻寬與 MediaMTX 讀取者名額
    return () => {
      cancelled = true;
      pc.ontrack = null;
      pc.onconnectionstatechange = null;
      pc.close();
      video.srcObject = null;
    };
  }, [whepUrl, channel, attempt]);

  if (!whepUrl) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-[var(--bg-surface-2)] text-center text-sm text-[var(--text-muted)]">
        {emptyLabel}
      </div>
    );
  }

  return (
    <div className="relative h-full w-full bg-black">
      <video ref={videoRef} autoPlay muted playsInline className="h-full w-full object-contain" />
      {overlayDeviceId !== null && state === 'connected' && (
        <SkeletonOverlay deviceId={overlayDeviceId} />
      )}
      {state !== 'connected' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[var(--bg-surface-2)] text-sm text-[var(--text-muted)]">
          <span>{state === 'failed' ? '連線失敗' : '連線中…'}</span>
          {state === 'failed' && (
            <button
              type="button"
              // 首頁四宮格把整格包成一個「點了放大／縮小」的按鈕，這顆重試鈕就在它裡面。
              // 不擋住事件冒泡的話，按重試會連帶把格子放大或縮小，看起來像沒重試。
              onClick={(e) => {
                e.stopPropagation();
                setAttempt((n) => n + 1);
              }}
              className="rounded-lg border border-[var(--border)] px-3 py-1 text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]"
            >
              重新連線
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default LiveStream;
