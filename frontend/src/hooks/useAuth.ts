import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authProvider, getStoredSession } from '../api/auth';
import type { AuthSession } from '../types';

export function useAuth() {
  const [session, setSession] = useState<AuthSession | null>(() => getStoredSession());
  const navigate = useNavigate();

  const logout = useCallback(() => {
    authProvider.logout();
    setSession(null);
    navigate('/login');
  }, [navigate]);

  return {
    session,
    role: session?.role ?? null,
    isAuthenticated: session !== null,
    logout,
  };
}
