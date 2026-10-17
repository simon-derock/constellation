import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

interface AsOf {
  day: number;
  setDay: (day: number) => void;
}

const Context = createContext<AsOf | null>(null);

export function AsOfProvider({ children, initial = 30 }: { children: ReactNode; initial?: number }) {
  const [day, setDay] = useState(initial);
  const value = useMemo(() => ({ day, setDay }), [day]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAsOf(): AsOf {
  const value = useContext(Context);
  if (!value) throw new Error("useAsOf needs an AsOfProvider");
  return value;
}
