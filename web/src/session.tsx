import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { ApiError, api, errorText, setCsrf } from './api';
import type { Session, User } from './types';
type SessionContext = {
  user: User | null;
  loading: boolean;
  error: string;
  accept: (value: Session) => void;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};
const Context = createContext<SessionContext | null>(null);
export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  function accept(session: Session) {
    setCsrf(session.csrf_token);
    setUser(session.user);
    setError('');
  }
  async function refresh() {
    try {
      accept(await api.me());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setUser(null);
        setCsrf('');
        setError('');
      } else setError(errorText(error));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    const expire = () => {
      setUser(null);
      setCsrf('');
    };
    window.addEventListener('wenli:session-expired', expire);
    void refresh();
    return () => window.removeEventListener('wenli:session-expired', expire);
  }, []);
  async function logout() {
    await api.logout();
    setCsrf('');
    setUser(null);
  }
  return (
    <Context.Provider value={{ user, loading, error, accept, refresh, logout }}>
      {children}
    </Context.Provider>
  );
}
export function useSession() {
  const value = useContext(Context);
  if (!value) throw new Error('Missing session provider');
  return value;
}
