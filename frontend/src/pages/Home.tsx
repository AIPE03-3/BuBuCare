import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCameras } from '../api/cameras';
import { LiveStream } from '../components/LiveStream';
import { StreamModeToggle, type StreamMode } from '../components/StreamModeToggle';
import { MonitorIcon } from '../components/icons';
import { useEvents } from '../hooks/eventsContext';
import { formatTime } from '../utils/time';
import { ALERT_LOG_ACTION_LABEL, CAMERA_LABEL, type AlertLogEntry, type Camera, type CareEvent } from '../types';

// 徽章配色：潛在危險／待處理皆實心紅（--danger，兩者都算「還沒人回應」，需要搶眼提醒），白字。
const ALERT_LOG_BADGE_CLASS: Record<AlertLogEntry['action'], string> = {
  hazard_detected: 'bg-[var(--danger)] text-white',
  pending: 'bg-[var(--danger)] text-white',
};

// pending 卡片外框：多一層淺紅框線標出「沒人處理」，潛在危險沿用一般卡片灰框。
const ALERT_LOG_CARD_BORDER_CLASS: Record<AlertLogEntry['action'], string> = {
  hazard_detected: 'border-[var(--border)]',
  pending: 'border-[var(--danger-bg)]',
};

// 單筆「未回應事件」卡：潛在危險偵測／待處理，兩態徽章配色。潛在危險附物品類型。時間顯示到分。
// 「待處理」可點擊重開全螢幕警示彈窗（傳 onClick），潛在危險沒有對應彈窗，不給 onClick。
function AlertLogCard({ entry, onClick }: { entry: AlertLogEntry; onClick?: () => void }) {
  const content = (
    <>
      <div className="flex min-w-0 items-center gap-2">
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${ALERT_LOG_BADGE_CLASS[entry.action]}`}
        >
          {ALERT_LOG_ACTION_LABEL[entry.action]}
        </span>
        <span className="truncate text-sm text-[var(--text-primary)]">
          {entry.cameraName}
          {entry.hazardObject && `・${entry.hazardObject}`}
        </span>
      </div>
      <span className="shrink-0 text-xs text-[var(--text-muted)]">{formatTime(entry.at)}</span>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={`flex w-full items-center justify-between gap-3 rounded-xl border bg-[var(--bg-surface)] px-4 py-3 text-left transition-colors duration-150 hover:bg-[var(--bg-surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] ${ALERT_LOG_CARD_BORDER_CLASS[entry.action]}`}
      >
        {content}
      </button>
    );
  }

  return (
    <div
      className={`flex items-center justify-between gap-3 rounded-xl border bg-[var(--bg-surface)] px-4 py-3 ${ALERT_LOG_CARD_BORDER_CLASS[entry.action]}`}
    >
      {content}
    </div>
  );
}

// pending 那幾行 log 不額外存資料，直接從後端持久化的 events 現算：只要事件 status 還是
// pending，重新整理後照樣算得出來，不會像原本存記憶體的 alertLog 一樣一刷新就不見。
function toPendingLogEntry(event: CareEvent): AlertLogEntry {
  return {
    id: `${event.id}-pending`,
    eventId: event.id,
    cameraName: `${event.camera.zone}（${event.camera.name}）`,
    action: 'pending',
    hazardObject: null,
    at: event.occurred_at,
  };
}

export function Home() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [streamMode, setStreamMode] = useState<StreamMode>('live');
  // 被放大的鏡頭 id；null＝四宮格模式
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const { events, alertLog, confirmedAlerts, reopenAlert, hazardEvents } = useEvents();

  // 合併顯示：alertLog（潛在危險偵測）＋ 現算的「待處理」
  // （events 裡還是 pending、且目前沒有全螢幕警示彈窗開著的，避免跟彈窗同時重複出現），依時間新到舊排序。
  const pendingLogEntries = events
    .filter((e) => e.status === 'pending' && !confirmedAlerts.some((a) => a.id === e.id))
    .map(toPendingLogEntry);
  const combinedLog = [...alertLog, ...pendingLogEntries].sort(
    (a, b) => new Date(b.at).getTime() - new Date(a.at).getTime(),
  );

  useEffect(() => {
    getCameras().then(setCameras);
  }, []);

  const unresolvedCount = events.filter((e) => e.status !== 'resolved').length;
  const onlineCameraCount = cameras.filter((c) => c.status === 'online').length;
  const hazardCount = hazardEvents.filter((e) => e.status !== 'resolved').length;

  // 四宮格只放「有串流網址」的鏡頭，取前四台。
  // 不用 cameras.slice(0, 4)：裝置清單含未接串流的鏡頭（如 VLM 測試裝置），
  // 依 device_id 取前四台會挑到四台沒有畫面的。
  const gridCameras = cameras.filter((c) => c.stream_url !== null).slice(0, 4);

  // 兩種模式播的是**同一條**乾淨串流；「偵測」只是多疊一層 canvas 骨架。
  // 2026-07-31 之前偵測模式是換另一條 AI 畫好框的串流（stream_url_detect），
  // 那條已停用（見 backend/streams/detections.py 的檔頭）。
  // 好處：切換模式不必重新協商 WebRTC，畫面不會黑一下。
  const overlayIdOf = (camera: Camera) => (streamMode === 'detect' ? camera.id : null);

  // 四台都沒接 AI 就不顯示切換鈕（按了也只是看到沒有骨架的同一個畫面）。
  // ⚠ 仍然看 stream_url_detect：那個欄位現在**不再拿來當播放網址**，但它的語意
  //   「這台鏡頭有接 AI」還在，是目前唯一能判斷這件事的欄位。
  const hasAnyDetect = gridCameras.some((c) => c.stream_url_detect !== null);

  return (
    <div className="flex flex-col gap-6">
      {/* 主版面：左 2/3（鏡頭＋三張統計卡）／右 1/3（切換選單＋log，隨左欄拉滿高） */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 左 2/3 */}
        <div className="flex flex-col gap-6 lg:col-span-2">
          {/* 即時影像：2×2 四宮格。點任一格放大成單一畫面、再點還原。
              放大時其餘三格改用 CSS 隱藏而非卸載——連線數上限與四宮格相同，
              但切換不必重新連線，不會有黑畫面。 */}
          <div className="flex items-center justify-end">
            {hasAnyDetect && <StreamModeToggle value={streamMode} onChange={setStreamMode} />}
          </div>

          <div className={expandedId === null ? 'grid grid-cols-2 gap-3' : 'grid grid-cols-1'}>
            {gridCameras.map((camera) => {
              const expanded = expandedId === camera.id;
              const hidden = expandedId !== null && !expanded;
              return (
                <button
                  key={camera.id}
                  type="button"
                  onClick={() => setExpandedId(expanded ? null : camera.id)}
                  aria-label={expanded ? `縮小 ${camera.name}` : `放大 ${camera.name}`}
                  className={`relative aspect-video w-full overflow-hidden rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] ${
                    hidden ? 'hidden' : ''
                  }`}
                >
                  <LiveStream
                    whepUrl={camera.stream_url}
                    channel={camera.stream_channel}
                    overlayDeviceId={overlayIdOf(camera)}
                  />
                  <span className="absolute left-3 top-3 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-0.5 text-xs text-[var(--text-secondary)]">
                    {camera.zone}（{camera.name}）
                  </span>
                </button>
              );
            })}

            {/* 裝置不足 4 台時補空格，維持 2×2 版面 */}
            {expandedId === null &&
              Array.from({ length: Math.max(0, 4 - gridCameras.length) }).map((_, i) => (
                <div
                  key={`empty-${i}`}
                  className="flex aspect-video w-full items-center justify-center rounded-2xl bg-[var(--bg-surface-2)] text-sm text-[var(--text-muted)]"
                >
                  {CAMERA_LABEL.LIVE_PLACEHOLDER}
                </div>
              ))}
          </div>

          {/* 三張統計卡：未結報事件／監控中鏡頭／潛在危險，並排於鏡頭下方；上下 7:3 分割 */}
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
            {/* 未結報事件：全站黑色化改版下唯一保留的品牌綠（--highlight），作為首頁最醒目的 CTA。 */}
            <div className="flex min-h-[210px] flex-col rounded-2xl bg-[var(--highlight)] p-6 text-white shadow-sm">
              <div className="flex flex-[7] flex-col justify-center">
                <p className="text-base text-white/70">未結報事件</p>
                <p className="mt-1 text-6xl font-semibold leading-none">{unresolvedCount}</p>
              </div>
              <div className="flex flex-[3] items-end justify-end">
                <Link
                  to="/events"
                  className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-[var(--highlight)] transition-colors duration-150 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--highlight)]"
                >
                  前往事件中心
                </Link>
              </div>
            </div>

            {/* 監控中鏡頭：純黑底白字（brand-dark） */}
            <div className="flex min-h-[210px] flex-col rounded-2xl bg-[var(--brand-dark)] p-6 text-white shadow-sm">
              <div className="flex flex-[7] flex-col justify-center">
                <p className="text-base text-white/70">監控中鏡頭</p>
                <p className="mt-1 text-6xl font-semibold leading-none">
                  {onlineCameraCount}
                  <span className="text-2xl font-normal text-white/60"> / {cameras.length}</span>
                </p>
              </div>
              <div className="flex flex-[3] items-end justify-end">
                <Link
                  to="/monitoring"
                  className="flex items-center gap-1.5 rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--brand-dark)]"
                >
                  <MonitorIcon className="h-4 w-4" aria-hidden="true" />
                  即時監控
                </Link>
              </div>
            </div>

            {/* 潛在危險（物件偵測）：不寫通報單、不跳彈窗，僅呈現偵測到的危險物品數量。
                數量為 0 時為淺灰卡（無需注意）；超過 0 時整卡轉紅（--danger）示警。 */}
            <div
              className={`flex min-h-[210px] flex-col rounded-2xl p-6 shadow-sm ${
                hazardCount > 0
                  ? 'bg-[var(--danger)] text-white'
                  : 'border border-[var(--border)] bg-[var(--bg-surface-2)] text-[var(--text-secondary)]'
              }`}
            >
              <div className="flex flex-[7] flex-col justify-center">
                <p className={hazardCount > 0 ? 'text-base text-white/70' : 'text-base text-[var(--text-secondary)]'}>
                  潛在危險
                </p>
                <p
                  className={`mt-1 text-6xl font-semibold leading-none ${
                    hazardCount > 0 ? 'text-white' : 'text-[var(--text-muted)]'
                  }`}
                >
                  {hazardCount}
                </p>
              </div>
              <div className="flex flex-[3] items-end justify-between gap-2">
                <p className={hazardCount > 0 ? 'text-xs text-white/70' : 'text-xs text-[var(--text-muted)]'}>
                  偵測到的危險物品數量
                </p>
                <Link
                  to="/events?tab=hazards"
                  className={`shrink-0 rounded-lg px-4 py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
                    hazardCount > 0
                      ? 'bg-white text-[var(--danger)] hover:opacity-90 focus-visible:ring-white focus-visible:ring-offset-[var(--danger)]'
                      : 'border border-[var(--text-secondary)] text-[var(--text-secondary)] hover:bg-[var(--brand-soft)] focus-visible:ring-[var(--brand)]'
                  }`}
                >
                  排除危險
                </Link>
              </div>
            </div>
          </div>
        </div>

        {/* 右 1/3：警示處理 log（隨左欄高度拉滿） */}
        <div className="flex flex-col gap-4 lg:col-span-1">
          {/* 未回應事件：潛在危險偵測＋待處理事件清單，最新在前；已接手／已誤報的不留在這裡。
              max-h 限制外框高度上限，超出改由內部清單捲動；沒有這個上限，CSS Grid 會讓
              軌道高度隨內容（筆數）無限撐高，overflow-y-auto 永遠不會真正生效。 */}
          <div className="flex min-h-[240px] max-h-[65vh] flex-1 flex-col gap-3 rounded-2xl border border-[var(--border)] bg-[var(--bg-surface-2)] p-4">
            <p className="text-sm font-medium text-[var(--text-secondary)]">未回應事件</p>
            {combinedLog.length === 0 ? (
              <div className="flex flex-1 items-center justify-center text-center text-sm text-[var(--text-muted)]">
                目前沒有未回應事件
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
                {combinedLog.map((entry) => (
                  <AlertLogCard
                    key={entry.id}
                    entry={entry}
                    onClick={
                      entry.action === 'pending'
                        ? () => {
                            const event = events.find((e) => e.id === entry.eventId);
                            if (event) reopenAlert(event);
                          }
                        : undefined
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

    </div>
  );
}

export default Home;
