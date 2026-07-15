import type { ComponentType, SVGProps } from 'react';
import { useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useCurrentUser } from '../hooks/useCurrentUser';
import {
  HexagonLogoIcon,
  HomeIcon,
  MonitorIcon,
  BellIcon,
  SparklesIcon,
  ClockIcon,
  CpuIcon,
  GearIcon,
  LogoutIcon,
  SearchIcon,
  ChevronDownIcon,
  MenuIcon,
  CloseIcon,
} from './icons';

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

interface NavItemProps {
  to: string;
  label: string;
  icon: IconComponent;
  active: boolean;
  onNavigate?: () => void;
}

function NavItem({ to, label, icon: Icon, active, onNavigate }: NavItemProps) {
  return (
    <Link
      to={to}
      onClick={onNavigate}
      className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2 ${
        active
          ? 'bg-[var(--brand-dark)] font-medium text-white'
          : 'text-[var(--text-secondary)] hover:bg-[var(--brand-soft)] hover:text-[var(--text-primary)]'
      }`}
    >
      <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
      {label}
    </Link>
  );
}

function NavGroupLabel({ children }: { children: string }) {
  return (
    <p className="px-3 pb-1 text-xs font-medium tracking-wide text-[var(--text-muted)]">{children}</p>
  );
}

const MAIN_NAV: { to: string; label: string; exact?: boolean; icon: IconComponent }[] = [
  { to: '/', label: '首頁', exact: true, icon: HomeIcon },
  { to: '/monitoring', label: '即時監控', icon: MonitorIcon },
  { to: '/events', label: '事件中心', icon: BellIcon },
];

interface UserMenuProps {
  name: string;
  employeeCode: string | null;
  isAdmin: boolean;
  onLogout: () => void;
  onNavigate?: () => void;
}

function UserMenu({ name, employeeCode, isAdmin, onLogout, onNavigate }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  return (
    <div className="relative">
      {open && (
        <div className="absolute inset-x-0 bottom-full z-10 mb-2 flex flex-col gap-1 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-1.5 shadow-sm">
          {isAdmin && (
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                onNavigate?.();
                navigate('/settings');
              }}
              className="flex items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-[var(--text-primary)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]"
            >
              <GearIcon className="h-5 w-5 shrink-0" aria-hidden="true" />
              設定
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onNavigate?.();
              onLogout();
            }}
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-[var(--text-primary)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]"
          >
            <LogoutIcon className="h-5 w-5 shrink-0" aria-hidden="true" />
            登出
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 rounded-xl bg-[var(--bg-surface)] p-3 text-left transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[var(--brand)] text-sm font-semibold text-white">
          {name.slice(0, 1)}
        </span>
        <div className="flex flex-1 flex-col overflow-hidden">
          <p className="truncate text-sm font-medium text-[var(--text-primary)]">
            {name}
            {employeeCode && `（${employeeCode}）`}
          </p>
          <p className="truncate text-xs text-[var(--text-muted)]">{isAdmin ? '系統管理者' : '護理站值班人員'}</p>
        </div>
        <ChevronDownIcon
          className={`h-4 w-4 shrink-0 text-[var(--text-muted)] transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>
    </div>
  );
}

export function AppLayout() {
  const { role, logout } = useAuth();
  const { name, employeeCode } = useCurrentUser();
  const { pathname } = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const isActive = (to: string, exact?: boolean) =>
    exact ? pathname === to : pathname.startsWith(to);

  const closeSidebar = () => setSidebarOpen(false);

  return (
    <div className="min-h-screen bg-[var(--bg-base)]">
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-[var(--overlay)] md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex h-screen w-[240px] shrink-0 flex-col justify-between bg-[var(--bg-surface-2)] p-4 transition-transform duration-150 md:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex min-h-0 flex-col gap-6 overflow-y-auto">
          <div className="flex items-center justify-between gap-2 px-2">
            <div className="flex items-center gap-2">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--brand-soft)] text-[var(--brand)]">
                <HexagonLogoIcon className="h-5 w-5" aria-hidden="true" />
              </span>
              <div className="flex flex-col leading-tight">
                <span className="text-sm font-semibold text-[var(--text-primary)]">BuBuCare</span>
                <span className="text-xs text-[var(--text-muted)]">跌倒偵測中控台</span>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              aria-label="關閉選單"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] md:hidden"
            >
              <CloseIcon className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>

          <div className="flex flex-col gap-1">
            <NavGroupLabel>總覽</NavGroupLabel>
            <nav className="flex flex-col gap-1">
              {MAIN_NAV.map((item) => (
                <NavItem
                  key={item.to}
                  to={item.to}
                  label={item.label}
                  icon={item.icon}
                  active={isActive(item.to, item.exact)}
                  onNavigate={closeSidebar}
                />
              ))}
            </nav>
          </div>

          <div className="flex flex-col gap-1">
            <NavGroupLabel>支援</NavGroupLabel>
            <nav className="flex flex-col gap-1">
              <div className="flex items-center justify-between rounded-xl px-3 py-2.5 text-sm text-[var(--text-muted)]">
                <span className="flex items-center gap-3">
                  <SparklesIcon className="h-5 w-5 shrink-0" aria-hidden="true" />
                通報單生成
                </span>
                <span className="text-xs">即將推出</span>
              </div>

              <NavItem
                to="/history"
                label="歷史紀錄"
                icon={ClockIcon}
                active={isActive('/history')}
                onNavigate={closeSidebar}
              />

              {role === 'admin' && (
                <NavItem
                  to="/mlops"
                  label="MLOps 面板(待確認)"
                  icon={CpuIcon}
                  active={isActive('/mlops')}
                  onNavigate={closeSidebar}
                />
              )}
            </nav>
          </div>
        </div>

        {name && (
          <div className="shrink-0 border-t border-[var(--border)] pt-3">
            <UserMenu
              name={name}
              employeeCode={employeeCode}
              isAdmin={role === 'admin'}
              onLogout={logout}
              onNavigate={closeSidebar}
            />
          </div>
        )}
      </aside>

      <div className="flex min-h-screen flex-col md:pl-[240px]">
        <main className="flex-1 p-4 sm:p-6">
          <header className="mb-6 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              aria-label="開啟選單"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] md:hidden"
            >
              <MenuIcon className="h-5 w-5" aria-hidden="true" />
            </button>

            <p className="min-w-0 flex-1 truncate text-xl font-semibold text-[var(--text-primary)]">
              {name ? `您好，${name}` : '您好'}
            </p>

            <label className="relative order-last w-full sm:order-none sm:w-64">
              <span className="sr-only">搜尋</span>
              <SearchIcon
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-muted)]"
                aria-hidden="true"
              />
              <input
                type="search"
                placeholder="搜尋"
                className="w-full rounded-full border border-[var(--border)] bg-[var(--bg-surface)] py-2 pl-9 pr-4 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]"
              />
            </label>
          </header>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default AppLayout;
