import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { BackButton } from '../components/BackButton';
import { ConfirmModal } from '../components/ConfirmModal';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { useEvents } from '../hooks/eventsContext';
import { getLatestReport, saveReport } from '../api/reports';
import { resolveEvent } from '../api/events';
import {
  REPORT_TYPES,
  REPORT_TYPE_TO_STAGE,
  REPORT_GENDERS,
  REPORT_WELFARE_OPTIONS,
  REPORT_DISTRICTS,
  REPORT_LOCATIONS,
  REPORT_INJURY_LEVELS,
  REPORT_NO_INJURY_DESC,
  REPORT_SERVICE_PERSONNEL,
  REPORT_SERVICE_PROCESS,
  REPORT_IMMEDIATE_NOTIFY,
  REPORT_HANDLING,
  REPORT_NO_INTERVENTION,
} from '../types';
import type { CareEvent, ReportFormData } from '../types';

// 陣列型多選欄位的加入／移除切換，供各「可複選」區塊共用。
function toggleArrayValue<T>(arr: readonly T[], value: T): T[] {
  return arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value];
}

// 進頁時由事件自動帶入：事件發生日期（年/月/日/時/分）與地點（帶入鏡頭區域，勾「其他」）。
// 其餘欄位事件無對應資料，留空手填。
// 通報別預設「初報」：本函式只在該事件尚無任何通報單時使用（首次填寫必為初報）；
// 續報／結報走已存紀錄帶入或 ?type 覆寫，不經此預設。
function buildInitialForm(event: CareEvent): ReportFormData {
  const d = new Date(event.occurred_at);
  const nowDate = new Date(); // 十一、通報日期＝進入本頁的當下時間
  return {
    reportType: '初報',
    caseName: '',
    caseIdNumber: '',
    gender: null,
    birthday: '',
    welfare: null,
    eventYear: String(d.getFullYear()),
    eventMonth: String(d.getMonth() + 1),
    eventDay: String(d.getDate()),
    eventHour: String(d.getHours()),
    eventMinute: String(d.getMinutes()),
    district: null,
    location: '其他',
    locationNote: `${event.camera.zone}（${event.camera.name}）`,
    impact: null,
    injuryLevel: null,
    serviceUnit: '',
    servicePersonnel: [],
    servicePersonnelNote: '',
    serviceProcess: [],
    serviceProcessNote: '',
    immediateNotify: [],
    eventNarrative: '',
    handling: [],
    handlingNote: '',
    noIntervention: [],
    noInterventionNote: '',
    reporterName: '',
    reporterUnit: '',
    reporterTitle: '',
    reportYear: String(nowDate.getFullYear()),
    reportMonth: String(nowDate.getMonth() + 1),
    reportDay: String(nowDate.getDate()),
    reportHour: String(nowDate.getHours()),
    reportMinute: String(nowDate.getMinutes()),
  };
}

function Section({ index, title, children }: { index: number; title: string; children: ReactNode }) {
  return (
    <section className="border-b border-[var(--border)] py-5 last:border-b-0">
      <h2 className="mb-3 text-base font-semibold text-[var(--text-primary)]">
        {index}、{title}
      </h2>
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}

const inputClass =
  'min-w-0 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]';

function TextField({
  label,
  value,
  onChange,
  className = '',
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <label className="inline-flex items-center gap-2 text-sm">
      <span className="shrink-0 text-[var(--text-secondary)]">{label}</span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        className={`${inputClass} ${className}`}
      />
    </label>
  );
}

// 日期用數字框（年/月/日/時/分），內建必填。
function NumberBox({
  value,
  onChange,
  ariaLabel,
  width,
}: {
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  width: string;
}) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      required
      aria-label={ariaLabel}
      className={`${inputClass} ${width}`}
    />
  );
}

// 單選：外觀為方框（沿用官方表單樣式），語意用 radio，確保鍵盤與讀屏正確。
function RadioOption({
  name,
  label,
  checked,
  onSelect,
}: {
  name: string;
  label: string;
  checked: boolean;
  onSelect: () => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 text-sm text-[var(--text-primary)]">
      <input
        type="radio"
        name={name}
        checked={checked}
        onChange={onSelect}
        required
        className="h-4 w-4 accent-[var(--brand)]"
      />
      {label}
    </label>
  );
}

function CheckOption({
  label,
  checked,
  onToggle,
}: {
  label: string;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 text-sm text-[var(--text-primary)]">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="h-4 w-4 accent-[var(--brand)]"
      />
      {label}
    </label>
  );
}

export function ReportFormPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { events, refreshEvents } = useEvents();
  const event = events.find((e) => e.id === id);
  const formRef = useRef<HTMLFormElement>(null);
  // 多選（核取方塊）群組的「至少選一項」錯誤；文字／數字／單選由原生 required 驗證，不進此集合。
  const [arrayErrors, setArrayErrors] = useState<Set<string>>(new Set());
  // 選「結報」＝結案並移入歷史，儲存前二次確認避免誤結案；true＝確認中。
  const [confirmFinal, setConfirmFinal] = useState(false);

  // ?type=續報｜結報：由詳情頁「續報／結報」鈕帶入，套用在初報單資料上並改通報別（自動勾選）。
  const requestedType = REPORT_TYPES.find((t) => t === searchParams.get('type')) ?? null;

  // 表單初值：已存過通報單則沿用最新一筆內容（自動帶入），否則由事件建空表；
  // 續報／結報再依 requestedType 覆寫通報別。api/reports 為 async（好換成後端 fetch），故走 effect 載入。
  const [form, setForm] = useState<ReportFormData | null>(null);
  // 每個事件只載入一次初值：SSE 更新會讓 event 物件換身分，若跟著重載會洗掉使用者填到一半的內容。
  const loadedEventIdRef = useRef<string | null>(null);
  // 通報者姓名自動帶入目前登入者（純前端，取 JWT 內的 full_name，不動資料庫）。
  const { name: currentUserName } = useCurrentUser();

  useEffect(() => {
    if (!event || loadedEventIdRef.current === event.id) return;
    const eventForLoad = event;
    getLatestReport(eventForLoad.id).then((latest) => {
      if (loadedEventIdRef.current === eventForLoad.id) return; // 併發載入（如 StrictMode 雙跑）已完成
      loadedEventIdRef.current = eventForLoad.id;
      const base = latest ? latest.form : buildInitialForm(eventForLoad);
      // 只在空白時填，不覆蓋既有值：續報／結報沿用初報內容時，原填表人的姓名要保留，
      // 不能被現在開啟頁面的人蓋掉（那是已送出的紀錄，不是這次要填的欄位）。
      const withReporter =
        base.reporterName || !currentUserName
          ? base
          : { ...base, reporterName: currentUserName };
      setForm(requestedType ? { ...withReporter, reportType: requestedType } : withReporter);
    });
  }, [event, requestedType, currentUserName]);

  if (!event) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">找不到此事件</p>
      </div>
    );
  }

  if (!form) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">載入中…</p>
      </div>
    );
  }

  const currentForm = form;
  // early return 後的 narrowed 事件常數，供下方巢狀函式引用（closure 內 event 會失去 narrowing）。
  const currentEvent = event;

  const update = <K extends keyof ReportFormData>(key: K, value: ReportFormData[K]) =>
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));

  // 多選群組必填（至少一項）；「無介入」子選項僅在勾選「無介入」時要求。
  // 第七題（服務過程／知悉時即通報）兩小點合計至少勾一項即可，不必兩點都勾。
  function collectArrayErrors(): Set<string> {
    const errors = new Set<string>();
    if (currentForm.servicePersonnel.length === 0) errors.add('servicePersonnel');
    if (currentForm.serviceProcess.length === 0 && currentForm.immediateNotify.length === 0) {
      errors.add('section7');
    }
    if (currentForm.handling.length === 0) errors.add('handling');
    if (currentForm.handling.includes('無介入') && currentForm.noIntervention.length === 0) {
      errors.add('noIntervention');
    }
    return errors;
  }

  // 儲存／輸出前統一驗證：原生 required 顧文字/數字/單選，collectArrayErrors 顧多選群組。
  function runIfValid(action: () => void) {
    const arrErr = collectArrayErrors();
    setArrayErrors(arrErr);
    const nativeOk = formRef.current?.reportValidity() ?? true;
    if (nativeOk && arrErr.size === 0) action();
  }

  const arrayErrorHint = (key: string) =>
    arrayErrors.has(key) ? (
      <p className="text-xs text-[var(--danger)]">請至少選擇一項</p>
    ) : null;

  // 儲存通報單後回事件詳情。通報階段不再由前端自行標記，改為存完重新向後端取事件。
  // 結報＝結案，但後端存通報單不會順帶結案（兩支端點），故另外呼叫 resolveEvent。
  // 先 await 再導頁：頁面已走、儲存卻失敗會騙到使用者。reportType 由原生 required 保證非空。
  async function persistAndReturn() {
    if (!currentForm.reportType) return;
    await saveReport(currentEvent.id, currentForm);
    if (REPORT_TYPE_TO_STAGE[currentForm.reportType] === 'final') {
      await resolveEvent(currentEvent.id);
    }
    await refreshEvents();
    navigate(`/events/${currentEvent.id}`);
  }

  // 儲存：先驗證全部必填；「結報」會結案，先進二次確認，其餘直接存並回事件詳情。
  function submit() {
    runIfValid(() => {
      if (currentForm.reportType === '結報') {
        setConfirmFinal(true);
        return;
      }
      void persistAndReturn();
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <BackButton />

      <h1 className="text-xl font-semibold text-[var(--text-primary)]">通報單填寫</h1>
      <p className="text-right text-sm text-[var(--text-secondary)]">＊ 所有欄位均為必填</p>

      <form ref={formRef} noValidate={false} onSubmit={(e) => e.preventDefault()}>
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] px-5 py-1 shadow-sm">
        {/* 通報別（單選，置於個案基本資料之上） */}
        <div className="border-b border-[var(--border)] py-5">
          <fieldset className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <legend className="mb-1 text-base font-semibold text-[var(--text-primary)]">通報別</legend>
            {REPORT_TYPES.map((t) => (
              <RadioOption
                key={t}
                name="reportType"
                label={t}
                checked={form.reportType === t}
                onSelect={() => update('reportType', t)}
              />
            ))}
          </fieldset>
        </div>

        {/* 一、個案基本資料 */}
        <Section index={1} title="個案基本資料">
          <div className="flex flex-wrap gap-4">
            <TextField label="姓名" value={form.caseName} onChange={(v) => update('caseName', v)} />
            <TextField
              label="身分證字號"
              value={form.caseIdNumber}
              onChange={(v) => update('caseIdNumber', v)}
            />
          </div>
          <fieldset className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <legend className="mb-1 text-sm text-[var(--text-secondary)]">性別</legend>
            {REPORT_GENDERS.map((g) => (
              <RadioOption
                key={g}
                name="gender"
                label={g}
                checked={form.gender === g}
                onSelect={() => update('gender', g)}
              />
            ))}
          </fieldset>
          <TextField label="生日" value={form.birthday} onChange={(v) => update('birthday', v)} />
          <fieldset className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <legend className="mb-1 text-sm text-[var(--text-secondary)]">福利身分</legend>
            {REPORT_WELFARE_OPTIONS.map((w) => (
              <RadioOption
                key={w}
                name="welfare"
                label={w}
                checked={form.welfare === w}
                onSelect={() => update('welfare', w)}
              />
            ))}
          </fieldset>
        </Section>

        {/* 二、事件發生日期 */}
        <Section index={2} title="事件發生日期">
          <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--text-primary)]">
            <NumberBox value={form.eventYear} onChange={(v) => update('eventYear', v)} ariaLabel="年" width="w-28" />
            年
            <NumberBox value={form.eventMonth} onChange={(v) => update('eventMonth', v)} ariaLabel="月" width="w-20" />
            月
            <NumberBox value={form.eventDay} onChange={(v) => update('eventDay', v)} ariaLabel="日" width="w-20" />
            日
            <NumberBox value={form.eventHour} onChange={(v) => update('eventHour', v)} ariaLabel="時" width="w-20" />
            時
            <NumberBox value={form.eventMinute} onChange={(v) => update('eventMinute', v)} ariaLabel="分" width="w-20" />
            分
          </div>
        </Section>

        {/* 三、行政區 */}
        <Section index={3} title="行政區">
          <fieldset className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4 lg:grid-cols-6">
            <legend className="sr-only">行政區</legend>
            {REPORT_DISTRICTS.map((district) => (
              <RadioOption
                key={district}
                name="district"
                label={district}
                checked={form.district === district}
                onSelect={() => update('district', district)}
              />
            ))}
          </fieldset>
        </Section>

        {/* 四、事件發生地點 */}
        <Section index={4} title="事件發生地點">
          <fieldset className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <legend className="sr-only">事件發生地點</legend>
            {REPORT_LOCATIONS.map((loc) => (
              <RadioOption
                key={loc}
                name="location"
                label={loc === '其他' ? '其他，請說明' : loc}
                checked={form.location === loc}
                onSelect={() => update('location', loc)}
              />
            ))}
          </fieldset>
          {form.location === '其他' && (
            <TextField
              label="說明"
              value={form.locationNote}
              onChange={(v) => update('locationNote', v)}
              className="flex-1"
            />
          )}
        </Section>

        {/* 五、事件發生後對個案的影響程度 */}
        <Section index={5} title="事件發生後對個案的影響程度">
          <fieldset className="flex flex-col gap-2">
            <legend className="sr-only">影響程度</legend>
            <p className="text-sm font-medium text-[var(--text-primary)]">有傷害→</p>
            <div className="flex flex-col gap-2 pl-5">
              {REPORT_INJURY_LEVELS.map(({ value, desc }) => (
                <label
                  key={value}
                  className="flex items-start gap-2 text-sm text-[var(--text-primary)]"
                >
                  <input
                    type="radio"
                    name="impact"
                    checked={form.impact === '有傷害' && form.injuryLevel === value}
                    onChange={() => {
                      update('impact', '有傷害');
                      update('injuryLevel', value);
                    }}
                    required
                    className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--brand)]"
                  />
                  <span>
                    <span className="font-medium">{value}</span>：{desc}
                  </span>
                </label>
              ))}
            </div>
            <label className="flex items-start gap-2 text-sm text-[var(--text-primary)]">
              <input
                type="radio"
                name="impact"
                checked={form.impact === '無傷害'}
                onChange={() => {
                  update('impact', '無傷害');
                  update('injuryLevel', null);
                }}
                required
                className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--brand)]"
              />
              <span>
                <span className="font-medium">無傷害</span>：{REPORT_NO_INJURY_DESC}
              </span>
            </label>
          </fieldset>
        </Section>

        {/* 六、與事件發生過程中有關聯的單位/人員 */}
        <Section index={6} title="與事件發生過程中有關聯的單位／人員">
          <TextField
            label="服務提供單位"
            value={form.serviceUnit}
            onChange={(v) => update('serviceUnit', v)}
            className="flex-1"
          />
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm text-[var(--text-secondary)]">服務提供人員</legend>
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
              {REPORT_SERVICE_PERSONNEL.map((person) => (
                <CheckOption
                  key={person}
                  label={person === '其他' ? '其他，請說明' : person}
                  checked={form.servicePersonnel.includes(person)}
                  onToggle={() =>
                    update('servicePersonnel', toggleArrayValue(form.servicePersonnel, person))
                  }
                />
              ))}
            </div>
            {form.servicePersonnel.includes('其他') && (
              <TextField
                label="說明"
                value={form.servicePersonnelNote}
                onChange={(v) => update('servicePersonnelNote', v)}
                className="flex-1"
              />
            )}
            {arrayErrorHint('servicePersonnel')}
          </fieldset>
        </Section>

        {/* 七、事件內容 */}
        <Section index={7} title="事件內容">
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm text-[var(--text-secondary)]">（一）服務過程</legend>
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
              {REPORT_SERVICE_PROCESS.map((item) => (
                <CheckOption
                  key={item}
                  label={item === '其他' ? '其他，請說明' : item}
                  checked={form.serviceProcess.includes(item)}
                  onToggle={() =>
                    update('serviceProcess', toggleArrayValue(form.serviceProcess, item))
                  }
                />
              ))}
            </div>
            {form.serviceProcess.includes('其他') && (
              <TextField
                label="說明"
                value={form.serviceProcessNote}
                onChange={(v) => update('serviceProcessNote', v)}
                className="flex-1"
              />
            )}
          </fieldset>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm text-[var(--text-secondary)]">
              （二）不限服務時段，知悉時即通報
            </legend>
            <div className="flex flex-col gap-2">
              {REPORT_IMMEDIATE_NOTIFY.map((item) => (
                <CheckOption
                  key={item}
                  label={item}
                  checked={form.immediateNotify.includes(item)}
                  onToggle={() =>
                    update('immediateNotify', toggleArrayValue(form.immediateNotify, item))
                  }
                />
              ))}
            </div>
          </fieldset>
          {/* （一）（二）合計至少勾一項即可，故錯誤提示放兩小點之後、整題僅一則。 */}
          {arrayErrors.has('section7') && (
            <p className="text-xs text-[var(--danger)]">（一）（二）請至少勾選一項</p>
          )}
        </Section>

        {/* 八、事發經過說明 */}
        <Section index={8} title="事發經過說明">
          <textarea
            value={form.eventNarrative}
            onChange={(e) => update('eventNarrative', e.target.value)}
            rows={6}
            required
            aria-label="事發經過說明"
            className="w-full resize-y rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]"
          />
          <div className="flex justify-end">
            {/* AI 摘要：本輪僅建立按鈕，功能待接 AI 摘要服務後實作。 */}
            <button
              type="button"
              onClick={() => console.info('[通報單] AI 摘要（功能待實作）', event.id)}
              className="rounded-md border border-[var(--brand)] bg-transparent px-3 py-1.5 text-sm font-medium text-[var(--brand)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
            >
              AI 摘要
            </button>
          </div>
        </Section>

        {/* 九、此事件發生後的立即處理（可複選） */}
        <Section index={9} title="此事件發生後的立即處理（可複選）">
          <div className="flex flex-col gap-2">
            <CheckOption
              label="無介入→"
              checked={form.handling.includes('無介入')}
              onToggle={() => update('handling', toggleArrayValue(form.handling, '無介入'))}
            />
            <div className="flex flex-col gap-2 pl-5">
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                {REPORT_NO_INTERVENTION.map((item) => (
                  <CheckOption
                    key={item}
                    label={item === '其他' ? '其他，請說明' : item}
                    checked={form.noIntervention.includes(item)}
                    onToggle={() =>
                      update('noIntervention', toggleArrayValue(form.noIntervention, item))
                    }
                  />
                ))}
              </div>
              {form.noIntervention.includes('其他') && (
                <TextField
                  label="說明"
                  value={form.noInterventionNote}
                  onChange={(v) => update('noInterventionNote', v)}
                  className="flex-1"
                />
              )}
              {arrayErrorHint('noIntervention')}
            </div>
            {REPORT_HANDLING.filter((item) => item !== '無介入').map((item) => (
              <CheckOption
                key={item}
                label={item === '其他' ? '其他，請說明' : item}
                checked={form.handling.includes(item)}
                onToggle={() => update('handling', toggleArrayValue(form.handling, item))}
              />
            ))}
            {form.handling.includes('其他') && (
              <TextField
                label="說明"
                value={form.handlingNote}
                onChange={(v) => update('handlingNote', v)}
                className="flex-1"
              />
            )}
            {arrayErrorHint('handling')}
          </div>
        </Section>

        {/* 十、通報者資料 */}
        <Section index={10} title="通報者資料">
          <TextField
            label="通報者姓名"
            value={form.reporterName}
            onChange={(v) => update('reporterName', v)}
          />
          <TextField
            label="單位"
            value={form.reporterUnit}
            onChange={(v) => update('reporterUnit', v)}
          />
          <TextField
            label="職稱"
            value={form.reporterTitle}
            onChange={(v) => update('reporterTitle', v)}
          />
        </Section>

        {/* 十一、通報日期（進頁自動帶入當下時間） */}
        <Section index={11} title="通報日期">
          <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--text-primary)]">
            <NumberBox value={form.reportYear} onChange={(v) => update('reportYear', v)} ariaLabel="通報年" width="w-28" />
            年
            <NumberBox value={form.reportMonth} onChange={(v) => update('reportMonth', v)} ariaLabel="通報月" width="w-20" />
            月
            <NumberBox value={form.reportDay} onChange={(v) => update('reportDay', v)} ariaLabel="通報日" width="w-20" />
            日
            <NumberBox value={form.reportHour} onChange={(v) => update('reportHour', v)} ariaLabel="通報時" width="w-20" />
            時
            <NumberBox value={form.reportMinute} onChange={(v) => update('reportMinute', v)} ariaLabel="通報分" width="w-20" />
            分
          </div>
        </Section>
      </div>
      </form>

      {/* 儲存：先驗證全部必填，通過即存到後端並更新通報狀態，回事件詳情。PDF 預覽只留在詳情頁。 */}
      <div className="flex justify-center">
        <button
          type="button"
          onClick={() => submit()}
          className="rounded-md bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90"
        >
          儲存
        </button>
      </div>

      {confirmFinal && (
        <ConfirmModal
          title="標記為結報"
          message="通報別為「結報」，儲存後事件將結案並移至歷史紀錄。確定要結報嗎？"
          onConfirm={() => {
            setConfirmFinal(false);
            void persistAndReturn();
          }}
          onCancel={() => setConfirmFinal(false)}
        />
      )}
    </div>
  );
}

export default ReportFormPage;
