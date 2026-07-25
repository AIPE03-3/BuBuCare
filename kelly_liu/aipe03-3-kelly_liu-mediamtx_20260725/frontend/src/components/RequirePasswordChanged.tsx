import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

// 尚未改臨時密碼（must_change_password=True）者，一律擋回強制改密碼頁。
// 只包住系統主區塊，不包 /force-change-password 本身，故不會自我跳轉。
export function RequirePasswordChanged({ children }: { children: ReactNode }) {
  const { mustChangePassword } = useAuth();

  if (mustChangePassword) {
    return <Navigate to="/force-change-password" replace />;
  }

  return <>{children}</>;
}

export default RequirePasswordChanged;
