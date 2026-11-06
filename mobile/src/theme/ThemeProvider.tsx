import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useColorScheme } from 'react-native';
import { palettes, type ColorScheme, type Palette } from './tokens';
import { readPref, writePref } from '../lib/prefs';

export type ThemePreference = 'system' | 'light' | 'dark';

type ThemeValue = {
  colors: Palette;
  scheme: ColorScheme;
  preference: ThemePreference;
  setPreference: (p: ThemePreference) => void;
};

const ThemeContext = createContext<ThemeValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const system = useColorScheme();
  const [preference, setPref] = useState<ThemePreference>('system');

  useEffect(() => {
    readPref('theme').then((v) => {
      if (v === 'light' || v === 'dark' || v === 'system') setPref(v);
    });
  }, []);

  const value = useMemo<ThemeValue>(() => {
    const scheme: ColorScheme =
      preference === 'system' ? (system === 'dark' ? 'dark' : 'light') : preference;
    return {
      colors: palettes[scheme],
      scheme,
      preference,
      setPreference: (p) => {
        setPref(p);
        writePref('theme', p);
      },
    };
  }, [preference, system]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error('useTheme outside ThemeProvider');
  return value;
}
