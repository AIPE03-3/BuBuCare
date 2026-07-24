import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCameras } from '../api/cameras';
import { DevTestPanel } from '../components/DevTestPanel'; // DEV-TEST：測試按鈕面板，移除測試功能時連同下方使用處一併刪除
import { MonitorIcon } from '../components/icons';
import { useEvents } from '../hooks/eventsContext';
import { formatTime } from '../utils/time';
import { ALERT_LOG_ACTION_LABEL, CAMERA_LABEL, type AlertLogEntry, type Camera, type CareEvent } from '../types';

// 切換鏡頭畫面選單。桌機置於右欄頂端、手機緊接鏡頭下方，故抽成元件於兩處各渲染一次
// （以 lg:hidden／hidden lg:block 控制，同一時間僅一個可見，不會重複讀屏）。
function CameraSelect({
  cameras,
  value,
  onChange,
}: {
  cameras: Camera[];
  value: number | null;
  onChange: (id: number) => void;
}) {
  return (
    <label className="block">
      <span className="sr-only">切換鏡頭畫面選單</span>
      <select
        value={value ?? ''}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg-surface-2)] px-4 py-3 text-sm font-medium text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]"
        aria-label="切換鏡頭畫面選單"
      >
        {cameras.length === 0 && <option value="">切換鏡頭畫面選單</option>}
        {cameras.map((camera) => (
          <option key={camera.id} value={camera.id}>
            {camera.zone}（{camera.name}）
          </option>
        ))}
      </select>
    </label>
  );
}

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
  const [selectedCameraId, setSelectedCameraId] = useState<number | null>(null);
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
    getCameras().then((list) => {
      setCameras(list);
      // 預設帶入第一支鏡頭，讓即時影像一載入就有選定畫面。
      setSelectedCameraId((prev) => prev ?? list[0]?.id ?? null);
    });
  }, []);

  const unresolvedCount = events.filter((e) => e.status !== 'resolved').length;
  const onlineCameraCount = cameras.filter((c) => c.status === 'online').length;
  const hazardCount = hazardEvents.filter((e) => e.status !== 'resolved').length;
  const selectedCamera = cameras.find((c) => c.id === selectedCameraId) ?? null;

  return (
    <div className="flex flex-col gap-6">
      {/* DEV-TEST：測試按鈕面板（模擬通知／清除測試資料），移除測試功能時刪除此區塊 */}
      <DevTestPanel />

      {/* 主版面：左 2/3（鏡頭＋三張統計卡）／右 1/3（切換選單＋log，隨左欄拉滿高） */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 左 2/3 */}
        <div className="flex flex-col gap-6 lg:col-span-2">
          {/* 即時影像：灰色占位框（不接真串流，比照全案影像慣例），左上角浮貼所選鏡頭名 */}
          <div className="relative flex aspect-video w-full items-center justify-center rounded-2xl bg-[var(--bg-surface-2)] text-center text-sm text-[var(--text-muted)]">
            {selectedCamera && (
              <span className="absolute left-3 top-3 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-0.5 text-xs text-[var(--text-secondary)]">
                {selectedCamera.zone}（{selectedCamera.name}）
              </span>
            )}
            {CAMERA_LABEL.SNAPSHOT_PLACEHOLDER}
          </div>

          {/* 手機：切換選單緊接鏡頭下方（桌機隱藏，改由右欄頂端顯示） */}
          <div className="lg:hidden">
            <CameraSelect cameras={cameras} value={selectedCameraId} onChange={setSelectedCameraId} />
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

        {/* 右 1/3：切換鏡頭畫面選單 ＋ 警示處理 log（隨左欄高度拉滿） */}
        <div className="flex flex-col gap-4 lg:col-span-1">
          {/* 桌機：選單在右欄頂端（手機隱藏，已顯示於鏡頭下方） */}
          <div className="hidden lg:block">
            <CameraSelect cameras={cameras} value={selectedCameraId} onChange={setSelectedCameraId} />
          </div>

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
