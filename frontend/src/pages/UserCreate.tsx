import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BackButton } from '../components/BackButton';
import { createUser } from '../api/users';
import { ROLE_LABEL, type ManagedUser } from '../types';

const PASSWORD_MIN_LENGTH = 6; // 對齊後端 POST /register 的 password min_length=6

// 下拉順序：一般值班人員最常建，放前面且為預設。
const ROLE_OPTIONS: ManagedUser['role'][] = ['staff', 'admin'];

const inputClass =
  'w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]';

// 新增使用者（admin-only）：填表後打 POST /register 開帳號。
// 新帳號後端自動設 must_change_password=true，新同事首次登入會被導去強制改密碼頁。
export function UserCreate() {
  const navigate = useNavigate();
  const [employeeId, setEmployeeId] = useState('');
  const [fullName, setFullName] = useState('');
  const [role, setRole] = useState<ManagedUser['role']>('staff');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    const trimmedId = employeeId.trim();
    const trimmedName = fullName.trim();
    const trimmedEmail = email.trim();

    if (!trimmedId) {
      setError('員工編號不可空白');
      return;
    }
    if (!trimmedName) {
      setError('姓名不可空白');
      return;
    }
    if (password.length < PASSWORD_MIN_LENGTH) {
      setError(`臨時密碼至少 ${PASSWORD_MIN_LENGTH} 碼`);
      return;
    }
    if (password !== passwordConfirm) {
      setError('兩次輸入的密碼不一致');
      return;
    }
    if (trimmedEmail && !trimmedEmail.includes('@')) {
      setError('Email 格式不正確');
      return;
    }

    setError(null);
    setSubmitting(true);
    try {
      await createUser({
        employee_id: trimmedId,
        full_name: trimmedName,
        role,
        password,
        email: trimmedEmail || undefined,
      });
      navigate('/users'); // 成功回列表，列表重抓會看到新帳號
    } catch (err) {
      // createUser 已把後端 detail（如「員編已存在」）當 Error message 拋出
      setError(err instanceof Error ? err.message : '建立失敗');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <BackButton />
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">新增使用者</h1>

      <div className="mx-auto flex w-full max-w-xl flex-col gap-6">
        <div className="flex flex-col gap-4 rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">員工編號</span>
            <input
              type="text"
              value={employeeId}
              onChange={(e) => setEmployeeId(e.target.value)}
              placeholder="請輸入員工編號"
              className={inputClass}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">姓名</span>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className={inputClass}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">角色</span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as ManagedUser['role'])}
              className={inputClass}
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">臨時密碼</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              placeholder={`至少 ${PASSWORD_MIN_LENGTH} 碼`}
              className={inputClass}
            />
            <span className="text-xs text-[var(--text-muted)]">
              新同事第一次登入時，會被要求自行設定新密碼。
            </span>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">確認臨時密碼</span>
            <input
              type="password"
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              autoComplete="new-password"
              placeholder="再次輸入臨時密碼"
              className={inputClass}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">Email（選填）</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="off"
              className={inputClass}
            />
          </label>

          {error && <p className="text-xs text-[var(--danger)]">{error}</p>}
        </div>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => navigate('/users')}
            className="rounded-md border border-[var(--text-secondary)] bg-transparent px-4 py-2 text-sm text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="rounded-md bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? '建立中…' : '建立帳號'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default UserCreate;
