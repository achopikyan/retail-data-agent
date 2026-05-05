import { createContext, ReactNode, useContext, useEffect, useState } from "react";

export type Role = "manager" | "gdpr_officer";

export interface UserState {
  userId: string;
  role: Role;
  setUserId: (id: string) => void;
  setRole: (r: Role) => void;
}

const STORAGE_KEY = "retail-agent.user";

const UserContext = createContext<UserState | null>(null);

interface Persisted {
  userId: string;
  role: Role;
}

function loadPersisted(): Persisted {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<Persisted>;
      if (parsed.userId && (parsed.role === "manager" || parsed.role === "gdpr_officer")) {
        return { userId: parsed.userId, role: parsed.role };
      }
    }
  } catch {
    // fall through
  }
  return { userId: "alice", role: "manager" };
}

export function UserProvider({ children }: { children: ReactNode }) {
  const initial = loadPersisted();
  const [userId, setUserId] = useState(initial.userId);
  const [role, setRole] = useState<Role>(initial.role);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ userId, role }));
  }, [userId, role]);

  return (
    <UserContext.Provider value={{ userId, role, setUserId, setRole }}>
      {children}
    </UserContext.Provider>
  );
}

export function useUser(): UserState {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser must be used within UserProvider");
  return ctx;
}
