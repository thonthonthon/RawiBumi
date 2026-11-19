/** Display and matching helpers for tinykeys-style key strings ("$mod+k", "Alt+1", "Shift+?"). */
const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

/** Physical key codes used in bindings (layout-independent, so Alt/⌥ combinations work on macOS). */
const CODES: Record<string, string> = { BracketLeft: "[", BracketRight: "]", Backslash: "\\", ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→" };

const LABELS: Record<string, string> = isMac
  ? { $mod: "⌘", Control: "⌃", Alt: "⌥", Shift: "⇧", Escape: "Esc", Enter: "↵", Backspace: "⌫", Delete: "Del", ...CODES }
  : { $mod: "Ctrl", Control: "Ctrl", Alt: "Alt", Shift: "Shift", Escape: "Esc", Enter: "Enter", Backspace: "Backspace", Delete: "Del", ...CODES };

/** "$mod+Shift+z" -> ["Ctrl", "Shift", "Z"] (or ⌘ ⇧ Z on macOS). */
export function keyParts(keys: string): string[] {
  return keys.split("+").map((part) => LABELS[part] ?? (part.length === 1 ? part.toUpperCase() : part));
}

/** True when focus is in a text field, where single-key shortcuts must not fire. */
export function typingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  if (el.isContentEditable || ["TEXTAREA", "SELECT"].includes(el.tagName)) return true;
  return el.tagName === "INPUT" && !["checkbox", "radio", "button", "submit", "reset", "range", "color", "file"].includes((el as HTMLInputElement).type);
}

export function dialogTarget(target: EventTarget | null): boolean {
  return !!(target as HTMLElement | null)?.closest?.('dialog[open], [role="dialog"], [role="alertdialog"]');
}
