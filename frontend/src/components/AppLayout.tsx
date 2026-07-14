import { Link, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useCurrentUser } from '../hooks/useCurrentUser';

interface NavItemProps {
  to: string;
  label: string;
  active: boolean;
}

function NavItem({ to, label, active }: NavItemProps) {
  return (
    <Link
      to={to}
      className={`border-l-[3px] px-4 py-2.5 text-sm transition-colors duration-150 ${
        active
          ? 'border-l-[var(--brand)] font-medium text-[var(--brand)]'
          : 'border-l-transparent text-[var(--text-primary)] hover:bg-[var(--brand-soft)]'
      }`}
    >
      {label}
    </Link>
  );
}

const MAIN_NAV: { to: string; label: string; exact?: boolean }[] = [
  { to: '/', label: '回首頁/總覽', exact: true },
  { to: '/monitoring', label: '即時監控' },
  { to: '/events', label: '事件中心' },
  { to: '/environment', label: '環境安全' },
];

export function AppLayout() {
  const { role, logout } = useAuth();
  const { name, employeeCode } = useCurrentUser();
  const { pathname } = useLocation();

  const isActive = (to: string, exact?: boolean) =>
    exact ? pathname === to : pathname.startsWith(to);

  return (
    <div className="flex min-h-screen bg-[var(--bg-base)]">
      <aside className="flex w-[220px] shrink-0 flex-col justify-between bg-[var(--bg-surface-2)]">
        <nav className="flex flex-col py-4">
          {MAIN_NAV.map((item) => (
            <NavItem key={item.to} to={item.to} label={item.label} active={isActive(item.to, item.exact)} />
          ))}

          <div className="flex items-center justify-between border-l-[3px] border-l-transparent px-4 py-2.5 text-sm text-[var(--text-muted)]">
            <span>Agent 洞察</span>
            <span className="text-xs">即將推出</span>
          </div>

          <NavItem to="/history" label="歷史紀錄" active={isActive('/history')} />

          {role === 'admin' && (
            <NavItem to="/mlops" label="MLOps 面板" active={isActive('/mlops')} />
          )}
        </nav>

        <div className="flex flex-col border-t border-[var(--border)] py-4">
          {role === 'admin' && (
            <NavItem to="/settings" label="設定" active={isActive('/settings')} />
          )}
          <button
            type="button"
            onClick={logout}
            className="px-4 py-2.5 text-left text-sm text-[var(--text-primary)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
          >
            登出
          </button>
        </div>
      </aside>

      <main className="flex-1 p-6">
        <header className="mb-4 flex items-center">
          {name && (
            <span className="text-sm text-[var(--text-secondary)]">
              您好！{name}
              {employeeCode && `（${employeeCode}）`}
            </span>
          )}
        </header>
        <Outlet />
      </main>
    </div>
  );
}

export default AppLayout;
