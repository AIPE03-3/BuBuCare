import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { role } = useAuth();

  if (role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

export default RequireAdmin;
