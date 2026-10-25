import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { authApi, onSessionLost, refreshSession, setAccessToken } from '../api/client.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // status: 'loading' (restoring from the refresh cookie) | 'signed-in' | 'signed-out'
  const [state, setState] = useState({ status: 'loading', user: null });

  useEffect(() => {
    let alive = true;
    refreshSession().then((data) => {
      if (!alive) return;
      setState(data ? { status: 'signed-in', user: data.user } : { status: 'signed-out', user: null });
    });
    const off = onSessionLost(() => setState({ status: 'signed-out', user: null }));
    return () => {
      alive = false;
      off();
    };
  }, []);

  const signIn = useCallback(async ({ email, password, remember, mode }) => {
    const data = await authApi.login({ email, password, remember, mode });
    setAccessToken(data.token);
    setState({ status: 'signed-in', user: data.user });
    return data.user;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      setAccessToken(null);
      setState({ status: 'signed-out', user: null });
    }
  }, []);

  const setUser = useCallback((user) => setState((s) => ({ ...s, user })), []);

  const value = useMemo(() => ({ ...state, signIn, signOut, setUser }), [state, signIn, signOut, setUser]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
