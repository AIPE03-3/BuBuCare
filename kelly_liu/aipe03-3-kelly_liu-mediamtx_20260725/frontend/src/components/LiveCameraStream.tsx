import { useCallback, useEffect, useRef, useState } from 'react';
import { getStreamToken } from '../api/streams';
import { connectWhep, type WhepSession } from '../utils/whep';

interface LiveCameraStreamProps {
  cameraName: string;
  cameraPath: string;
}

const MEDIAMTX_BASE_URL = (
  // MediaMTX 主機位置屬於部署機敏資料；正式環境請在未提交 Git 的 .env 設定。
  import.meta.env.VITE_MEDIAMTX_BASE_URL ?? 'https://localhost:8889'
).replace(/\/$/, '');
const RETRY_DELAY_MS = 3000;

export function LiveCameraStream({ cameraName, cameraPath }: LiveCameraStreamProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const sessionRef = useRef<WhepSession | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const aliveRef = useRef(true);
  const [status, setStatus] = useState('準備連線');
  const [connecting, setConnecting] = useState(false);

  const disconnect = useCallback(() => {
    if (retryTimerRef.current !== null) window.clearTimeout(retryTimerRef.current);
    retryTimerRef.current = null;
    sessionRef.current?.close();
    sessionRef.current = null;
  }, []);

  const connect = useCallback(async () => {
    const video = videoRef.current;
    if (!video || !aliveRef.current) return;
    disconnect();
    setConnecting(true);
    setStatus('正在取得觀看權限…');

    try {
      const { token } = await getStreamToken(cameraPath);
      if (!aliveRef.current) return;
      setStatus('正在連線攝影機…');
      sessionRef.current = await connectWhep(
        video,
        `${MEDIAMTX_BASE_URL}/${encodeURIComponent(cameraPath)}/whep`,
        token,
        (state) => {
          if (!aliveRef.current) return;
          if (state === 'connected') setStatus('即時影像');
          if (state === 'failed' || state === 'disconnected') {
            setStatus('串流中斷，正在重新連線…');
            disconnect();
            retryTimerRef.current = window.setTimeout(() => void connect(), RETRY_DELAY_MS);
          }
        },
      );
      setStatus('即時影像');
    } catch (error) {
      if (!aliveRef.current) return;
      const message = error instanceof Error ? error.message : '未知錯誤';
      if (message.includes('401')) {
        setStatus('請先登入，再觀看即時影像');
      } else {
        setStatus(
          cameraPath === 'iphone_camera'
            ? '等待手機開始發布，將自動重試…'
            : '攝影機暫時無法連線，將自動重試…',
        );
        retryTimerRef.current = window.setTimeout(() => void connect(), RETRY_DELAY_MS);
      }
    } finally {
      if (aliveRef.current) setConnecting(false);
    }
  }, [cameraPath, disconnect]);

  useEffect(() => {
    aliveRef.current = true;
    void connect();
    return () => {
      aliveRef.current = false;
      disconnect();
    };
  }, [connect, disconnect]);

  return (
    <div className="overflow-hidden rounded-2xl border border-[var(--border)] bg-black shadow-sm">
      <div className="relative aspect-video">
        <video
          ref={videoRef}
          className="h-full w-full object-contain"
          aria-label={`${cameraName} 即時監視畫面`}
          autoPlay
          muted
          playsInline
        />
        <span className="absolute left-3 top-3 rounded-md bg-black/70 px-2.5 py-1 text-xs text-white">
          {cameraName}
        </span>
        <span className="absolute right-3 top-3 flex items-center gap-1.5 rounded-md bg-black/70 px-2.5 py-1 text-xs text-white">
          <span className="h-2 w-2 rounded-full bg-red-500" aria-hidden="true" />
          LIVE
        </span>
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-white/10 bg-[var(--bg-surface-2)] px-4 py-3">
        <span className="text-sm text-[var(--text-secondary)]" role="status">
          {status}
        </span>
        <button
          type="button"
          disabled={connecting}
          onClick={() => void connect()}
          className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--text-primary)] disabled:opacity-50"
        >
          重新連線
        </button>
      </div>
    </div>
  );
}
