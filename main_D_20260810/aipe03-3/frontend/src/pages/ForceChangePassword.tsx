// 強制改密碼頁：新帳號首次登入、或被 admin 重設密碼（must_change_password=True）者，
// 登入後被導來此頁，改完密碼才放行進系統。路由守衛 RequirePasswordChanged 負責攔截。
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { changeMyPassword } from '../api/auth';
import { useAuth } from '../hooks/useAuth';

const MIN_LENGTH = 6;

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : '發生未知錯誤';
}

export function ForceChangePassword() {
  const navigate = useNavigate();
  const { logout } = useAuth();

  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // 前端先擋明顯錯誤，減少白打後端一趟；訊息只在使用者已開始輸入後才顯示，避免一進頁面就紅字。
  function validate(): string | null {
    if (newPassword.length < MIN_LENGTH) return `新密碼至少 ${MIN_LENGTH} 碼`;
    if (newPassword === oldPassword) return '新密碼不可與目前密碼相同';
    if (confirmPassword !== newPassword) return '兩次新密碼不一致';
    return null;
  }

  const validationError = validate();
  const canSubmit =
    oldPassword.length > 0 && newPassword.length > 0 && confirmPassword.length > 0 &&
    validationError === null && !submitting;

  async function handleSubmit() {
    const localError = validate();
    if (localError) {
      setError(localError);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await changeMyPassword(oldPassword, newPassword);
      navigate('/'); // 改成功：session 旗標已歸 false，主區塊守衛不再攔截
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  const inputClass =
    'mt-1 w-full rounded-md border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none transition-colors duration-150 focus:border-[var(--brand)]';

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--bg-base)] p-4">
      <div className="w-full max-w-[380px] rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-6 sm:p-8">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">設定新密碼</h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          為了帳號安全，請先設定專屬於你的新密碼，完成後即可進入系統。
        </p>

        <div className="mt-6">
          <label htmlFor="old-password" className="text-sm text-[var(--text-primary)]">
            目前密碼
          </label>
          <input
            id="old-password"
            type="password"
            autoComplete="current-password"
            value={oldPassword}
            onChange={(e) => setOldPassword(e.target.value)}
            className={inputClass}
            placeholder="••••••"
          />
        </div>

        <div className="mt-4">
          <label htmlFor="new-password" className="text-sm text-[var(--text-primary)]">
            新密碼
          </label>
          <input
            id="new-password"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className={inputClass}
            placeholder={`至少 ${MIN_LENGTH} 碼`}
          />
        </div>

        <div className="mt-4">
          <label htmlFor="confirm-password" className="text-sm text-[var(--text-primary)]">
            確認新密碼
          </label>
          <input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && canSubmit) handleSubmit();
            }}
            className={inputClass}
            placeholder="再輸入一次新密碼"
          />
        </div>

        {error && <p className="mt-2 text-xs text-[var(--danger)]">{error}</p>}

        <button
          type="button"
          disabled={!canSubmit}
          onClick={handleSubmit}
          className="mt-5 w-full rounded-md bg-[var(--brand)] py-2 text-sm font-medium text-white transition-colors duration-150 disabled:opacity-50"
        >
          {submitting ? '設定中...' : '設定新密碼'}
        </button>

        <button
          type="button"
          onClick={logout}
          className="mt-3 w-full text-xs text-[var(--text-secondary)] transition-colors duration-150 hover:text-[var(--text-primary)]"
        >
          先登出
        </button>
      </div>
    </div>
  );
}

export default ForceChangePassword;
