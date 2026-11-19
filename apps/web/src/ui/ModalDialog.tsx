import { useEffect, useRef, type ReactNode } from "react";

/** Native modal semantics: focus containment, inert background, Escape and focus return. */
export function ModalDialog({ children, label, onClose, small = false, alert = false, wide = false }: {
  children: ReactNode; label: string; onClose: () => void; small?: boolean; alert?: boolean; wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef(document.activeElement instanceof HTMLElement ? document.activeElement : null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    if (alert) dialog.querySelector<HTMLButtonElement>('[data-cancel]')?.focus();
    return () => { dialog.close(); if (opener.current?.isConnected) opener.current.focus(); };
  }, [alert]);
  return (
    <dialog ref={ref} className={`modal${small ? " modal--small" : ""}${wide ? " modal--wide" : ""}`} aria-label={label}
      role={alert ? "alertdialog" : undefined} onCancel={onClose}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key !== "Tab") return;
        const controls = [...e.currentTarget.querySelectorAll<HTMLElement>('button, input, textarea, select, a[href], [tabindex]')]
          .filter((el) => el.tabIndex >= 0 && !el.matches(':disabled') && el.getClientRects().length > 0);
        const first = controls[0], last = controls.at(-1);
        if ((!e.shiftKey && document.activeElement === last) || (e.shiftKey && document.activeElement === first)) {
          e.preventDefault(); (e.shiftKey ? last : first)?.focus();
        }
      }} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal__content">{children}</div>
    </dialog>
  );
}
