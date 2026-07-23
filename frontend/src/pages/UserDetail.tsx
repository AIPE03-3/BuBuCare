import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { BackButton } from '../components/BackButton';
import { getUserById, updateUser } from '../api/users';
import { ROLE_LABEL, type ManagedUser } from '../types';

const PASSWORD_MIN_LENGTH = 6; // 對齊後端 PATCH /users/{id}/password 的 min_length=6

const inputClass =
  'w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]';

// 唯讀資訊列（工號、角色）。
function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--border)] py-3 text-sm last:border-b-0">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <span className="text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

// 使用者詳情：修改名稱與密碼（demo 存 localStorage）。密碼留空＝不變更。
export function UserDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [user, setUser] = useState<ManagedUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    getUserById(id).then((found) => {
      setUser(found);
      if (found) setName(found.name);
      setLoading(false);
    });
  }, [id]);

  if (loading) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">載入中…</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">找不到此使用者</p>
      </div>
    );
  }

  const currentUser = user; // early return 後的 narrowed 常數，供下方 async 函式引用

  async function handleSave() {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError('名稱不可空白');
      return;
    }
    // 密碼選填：任一欄有填才驗證長度與一致性。
    if (password || passwordConfirm) {
      if (password.length < PASSWORD_MIN_LENGTH) {
        setError(`密碼至少 ${PASSWORD_MIN_LENGTH} 碼`);
        return;
      }
      if (password !== passwordConfirm) {
        setError('兩次輸入的密碼不一致');
        return;
      }
    }
    await updateUser(currentUser.id, {
      name: trimmedName,
      password: password || undefined,
    });
    navigate('/users');
  }

  return (
    <div className="flex flex-col gap-4">
      <BackButton />
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">編輯使用者</h1>

      <div className="mx-auto flex w-full max-w-xl flex-col gap-6">
        {/* 唯讀資訊 */}
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
          <InfoRow label="工號" value={currentUser.employee_code} />
          <InfoRow label="角色" value={ROLE_LABEL[currentUser.role]} />
        </div>

        {/* 可編輯：名稱與密碼 */}
        <div className="flex flex-col gap-4 rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">名稱</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputClass}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">新密碼</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              placeholder="留空表示不變更"
              className={inputClass}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--text-secondary)]">確認新密碼</span>
            <input
              type="password"
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              autoComplete="new-password"
              placeholder="再次輸入新密碼"
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
            onClick={handleSave}
            className="rounded-md bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90"
          >
            儲存
          </button>
        </div>
      </div>
    </div>
  );
}

export default UserDetail;
