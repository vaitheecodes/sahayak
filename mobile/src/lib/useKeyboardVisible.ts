import { useEffect, useState } from 'react';
import { Keyboard, Platform } from 'react-native';

// Shorter than any docked keyboard; floating keyboards and toolbars report
// little or no height and leave the gesture bar uncovered.
const DOCKED_MIN_HEIGHT = 120;

/** Whether a docked on-screen keyboard is up. It covers the gesture bar, so
 *  a bottom bar only needs the safe-area inset while it's down. */
export function useKeyboardVisible(): boolean {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const show = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hide = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const subs = [
      Keyboard.addListener(show, (e) => setVisible((e?.endCoordinates?.height ?? 0) >= DOCKED_MIN_HEIGHT)),
      Keyboard.addListener(hide, () => setVisible(false)),
    ];
    return () => subs.forEach((s) => s.remove());
  }, []);
  return visible;
}
