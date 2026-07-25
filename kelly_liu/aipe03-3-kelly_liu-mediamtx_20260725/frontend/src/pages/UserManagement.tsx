import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getUsers } from '../api/users';
import { ROLE_LABEL, type ManagedUser } from '../types';

// 管理使用者：列出所有使用者（demo 假資料），點列進入詳情頁修改名稱與密碼。
export function UserManagement() {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    getUsers().then(setUsers);
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">管理使用者</h1>
        <button
          type="button"
          onClick={() => navigate('/users/new')}
          className="shrink-0 rounded-md bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90"
        >
          ＋ 新增使用者
        </button>
      </div>
      <p className="text-sm text-[var(--text-secondary)]">點選任一位使用者可修改名稱與密碼。</p>

      {/* 桌機：表格 */}
      <div className="hidden overflow-x-auto rounded-xl border border-[var(--border)] md:block">
        <table className="w-full text-left text-sm">
          <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
            <tr>
              <th className="px-4 py-3 font-medium">名稱</th>
              <th className="px-4 py-3 font-medium">工號</th>
              <th className="px-4 py-3 font-medium">角色</th>
              <th className="px-4 py-3" aria-hidden="true" />
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr
                key={user.id}
                onClick={() => navigate(`/users/${user.id}`)}
                className="cursor-pointer border-t border-[var(--border)] bg-[var(--bg-surface)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
              >
                <td className="px-4 py-3 font-medium text-[var(--text-primary)]">{user.name}</td>
                <td className="px-4 py-3 text-[var(--text-secondary)]">{user.employee_code}</td>
                <td className="px-4 py-3 text-[var(--text-secondary)]">{ROLE_LABEL[user.role]}</td>
                <td className="px-4 py-3 text-right text-[var(--text-muted)]" aria-hidden="true">
                  ›
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 手機：卡片 */}
      <ul className="flex flex-col gap-3 md:hidden">
        {users.map((user) => (
          <li key={user.id}>
            <button
              type="button"
              onClick={() => navigate(`/users/${user.id}`)}
              className="flex w-full items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4 text-left transition-colors duration-150 hover:bg-[var(--brand-soft)]"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-[var(--text-primary)]">{user.name}</p>
                <p className="truncate text-xs text-[var(--text-muted)]">
                  {user.employee_code}・{ROLE_LABEL[user.role]}
                </p>
              </div>
              <span aria-hidden="true" className="shrink-0 text-[var(--text-muted)]">
                ›
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default UserManagement;
