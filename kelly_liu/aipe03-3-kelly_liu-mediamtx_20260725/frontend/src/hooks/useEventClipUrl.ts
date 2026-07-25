import { useEffect, useState } from 'react';
import { getEventMedia } from '../api/events';

interface ClipResult {
  id: string | undefined;
  clipUrl: string | null;
  error: boolean;
}

// 共用 hook：換發事件的限時影片網址，供事件詳情頁／全螢幕警示／誤報確認彈窗共用。
// eventId 換了就重抓；網址約 1 小時失效，故不快取、每次進場重新呼叫。
// loading 狀態靠比對「上次抓回結果所屬的 id」與「目前的 eventId」推得，
// 避免在 effect 內同步呼叫 setState（該作法會觸發 cascading render，ESLint 會擋下來）。
export function useEventClipUrl(eventId: string | undefined) {
  const [result, setResult] = useState<ClipResult>({
    id: undefined,
    clipUrl: null,
    error: false,
  });

  useEffect(() => {
    if (!eventId) return;

    let cancelled = false;

    getEventMedia(eventId)
      .then((media) => {
        if (cancelled) return;
        setResult({ id: eventId, clipUrl: media.clip_url, error: false });
      })
      .catch(() => {
        if (cancelled) return;
        setResult({ id: eventId, clipUrl: null, error: true });
      });

    return () => {
      cancelled = true;
    };
  }, [eventId]);

  if (!eventId) {
    return { clipUrl: null, loading: false, error: false };
  }

  const loading = result.id !== eventId;
  return {
    clipUrl: loading ? null : result.clipUrl,
    loading,
    error: loading ? false : result.error,
  };
}
