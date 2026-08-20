import { useEffect } from "react";

export interface Shortcut {
  key: string;
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  handler: () => void;
  preventDefault?: boolean;
}

export function useKeyboardShortcuts(shortcuts: Shortcut[]) {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      for (const s of shortcuts) {
        const keyMatch = e.key.toLowerCase() === s.key.toLowerCase();
        const ctrlMatch = !!s.ctrl === e.ctrlKey;
        const shiftMatch = !!s.shift === e.shiftKey;
        const altMatch = !!s.alt === e.altKey;
        if (keyMatch && ctrlMatch && shiftMatch && altMatch) {
          if (s.preventDefault !== false) e.preventDefault();
          s.handler();
        }
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [shortcuts]);
}
