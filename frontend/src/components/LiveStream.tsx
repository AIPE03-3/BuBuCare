import { useEffect, useRef, useState } from 'react';
import { negotiateWhep } from '../api/streams';
import { CAMERA_LABEL } from '../types';

type ConnectionState = 'connecting' | 'connected' | 'failed';

interface LiveStreamProps {
  /** 完整 WHEP 網址；null＝這個環境沒有這條串流，顯示占位框 */
  whepUrl: string | null;
  /** 占位框文字。預設「鏡頭即時影像」；偵測模式下沒有 AI 的鏡頭傳「此鏡頭無 AI 偵測」 */
  emptyLabel?: string;
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

export function LiveStream({ whepUrl, emptyLabel = CAMERA_LABEL.LIVE_PLACEHOLDER }: LiveStreamProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<ConnectionState>('connecting');
  // 遞增此值即觸發重新連線（重試按鈕用）
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const video = videoRef.current;
    if (!whepUrl || !video) return;

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
        const answer = await negotiateWhep(whepUrl, pc.localDescription?.sdp ?? '');
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
  }, [whepUrl, attempt]);

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
      {state !== 'connected' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[var(--bg-surface-2)] text-sm text-[var(--text-muted)]">
          <span>{state === 'failed' ? '連線失敗' : '連線中…'}</span>
          {state === 'failed' && (
            <button
              type="button"
              onClick={() => setAttempt((n) => n + 1)}
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
