import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setCsrf, type Me } from "./api";

type AuthState = { me: Me | null; loading: boolean; reload: () => void };
const AuthContext = createContext<AuthState>({ me: null, loading: true, reload: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = () => {
    setLoading(true);
    api
      .get("/api/me")
      .then((data: Me) => {
        setMe(data);
        if (data.csrf) setCsrf(data.csrf);
      })
      .catch(() => setMe({ authenticated: false, rarities: [] }))
      .finally(() => setLoading(false));
  };

  useEffect(reload, []);

  return <AuthContext.Provider value={{ me, loading, reload }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
