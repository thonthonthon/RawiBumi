import { ReactNode, useId, useState } from "react";
import { PENDING } from "../pending";

export function Button({
  children,
  onClick,
  disabled,
  tone = "default",
  title,
  type = "button",
  small,
  cancel = false
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "default" | "primary" | "ghost" | "danger";
  title?: string;
  type?: "button" | "submit";
  small?: boolean;
  cancel?: boolean;
}) {
  return (
    <button type={type} className={`btn btn--${tone}${small ? " btn--sm" : ""}`} onClick={onClick} disabled={disabled} title={title} data-cancel={cancel || undefined}>
      {children}
    </button>
  );
}

/** Marks a control whose engine endpoint does not exist yet. Hover shows the endpoint to build. */
export function NotWired({ id, compact }: { id: string; compact?: boolean }) {
  const e = PENDING[id];
  const tip = e ? `${e.method} ${e.path}\n${e.purpose}\n${e.specRef}` : id;
  return (
    <span className={compact ? "notwired notwired--compact" : "notwired"} title={tip}>
      Not wired
    </span>
  );
}

/** Wraps a group of controls that are available in the UI but not yet backed by the engine. */
export function PendingBlock({ id, children, note }: { id: string; children: ReactNode; note?: string }) {
  const e = PENDING[id];
  return (
    <div className="pending-block">
      <div className="pending-block__head">
        <NotWired id={id} />
        <span className="pending-block__path">{e ? `${e.method} ${e.path}` : id}</span>
      </div>
      {note && <p className="pending-block__note">{note}</p>}
      {children}
    </div>
  );
}

/**
 * A collapsible section. Uncontrolled by default (`defaultOpen`); pass `open` and
 * `onOpenChange` to control it. `summary` is shown in the header while closed.
 */
// The viewer's own open/closed choice per section title, kept in this browser only (never in the project).
const SECTION_KEY = "rawibumi.section.";
function rememberedOpen(title: string): boolean | undefined {
  try {
    const value = window.localStorage.getItem(SECTION_KEY + title);
    return value === null ? undefined : value === "1";
  } catch {
    return undefined;
  }
}
function rememberOpen(title: string, open: boolean) {
  try {
    window.localStorage.setItem(SECTION_KEY + title, open ? "1" : "0");
  } catch {
    // Storage blocked or full: the section still toggles, it just is not remembered.
  }
}

export function Section({
  title,
  children,
  aside,
  primary = false,
  defaultOpen = primary,
  open: openProp,
  onOpenChange,
  summary
}: {
  title: string;
  children: ReactNode;
  aside?: ReactNode;
  /** UXF1 (U2-16): the section holding the active work opens by default; every other section starts collapsed. */
  primary?: boolean;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  summary?: ReactNode;
}) {
  const [choice, setChoice] = useState<{ title: string; open: boolean } | null>(null);
  const open = openProp ?? (choice?.title === title ? choice.open : rememberedOpen(title) ?? defaultOpen);
  const bodyId = useId();
  const toggle = () => {
    if (openProp === undefined) setChoice({ title, open: !open });
    rememberOpen(title, !open);
    onOpenChange?.(!open);
  };
  return (
    <section className={open ? "section" : "section section--closed"}>
      <header className="section__head">
        <button type="button" className="section__toggle" onClick={toggle} aria-expanded={open} aria-controls={open ? bodyId : undefined}>
          <span className="section__chev" aria-hidden>
            {open ? "▾" : "▸"}
          </span>
          {title}
        </button>
        {aside}
      </header>
      {!open && summary && <div className="section__summary">{summary}</div>}
      {open && (
        <div className="section__body" id={bodyId}>
          {children}
        </div>
      )}
    </section>
  );
}

export function Field({ label, unit, children, hint }: { label: string; unit?: string; children: ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span className="field__label">
        {label}
        {unit && <span className="field__unit">{unit}</span>}
      </span>
      {children}
      {hint && <span className="field__hint">{hint}</span>}
    </label>
  );
}

/** Like Field, for a group of controls (radio buttons): a <label> may hold only one control. */
export function FieldGroup({ label, unit, children, hint }: { label: string; unit?: string; children: ReactNode; hint?: string }) {
  return (
    <div className="field" role="group" aria-label={label}>
      <span className="field__label">
        {label}
        {unit && <span className="field__unit">{unit}</span>}
      </span>
      {children}
      {hint && <span className="field__hint">{hint}</span>}
    </div>
  );
}

export function NumberInput({
  value,
  onChange,
  step = 0.1,
  min,
  max,
  disabled,
  commit: commitMode = false
}: {
  value: number;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  max?: number;
  disabled?: boolean;
  /** UXF1 (U2-1): for fields whose onChange saves to the server. Typing only edits the text; Enter, leaving the
   *  field or a stepper calls onChange once. Esc restores. Without it, onChange follows every keystroke (drafts). */
  commit?: boolean;
}) {
  const [text, setText] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(false);
  const shown = Number.isFinite(value) ? String(Math.round(value * 1e6) / 1e6) : "";
  // Range checks stay with the callers, which show their own messages; only a non-number is refused here.
  const commit = (raw: string) => {
    const v = Number(raw);
    const ok = raw.trim() !== "" && Number.isFinite(v);
    setText(null);
    setInvalid(!ok);
    if (ok && !disabled) onChange(v);
  };
  if (!commitMode)
    return (
      <input
        className="input input--num"
        type="number"
        value={text ?? shown}
        step={step}
        min={min}
        max={max}
        disabled={disabled}
        onChange={(e) => {
          setText(e.target.value);
          const v = Number(e.target.value);
          if (e.target.value !== "" && Number.isFinite(v)) onChange(v);
        }}
        onBlur={() => setText(null)}
      />
    );
  return (
    <input
      className="input input--num"
      type="number"
      value={text ?? shown}
      step={step}
      min={min}
      max={max}
      // A field being edited stays enabled while another save runs, so typed text and focus survive.
      disabled={disabled && text === null}
      aria-invalid={invalid || undefined}
      onChange={(e) => {
        setInvalid(false);
        // Spinner buttons and arrow keys change the value without an inputType; typing always has one.
        if (!(e.nativeEvent as InputEvent).inputType) commit(e.target.value);
        else setText(e.target.value);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" && text !== null) commit(text);
        if (e.key === "Escape" && text !== null) { setText(null); setInvalid(false); }
      }}
      onBlur={() => { if (text !== null) commit(text); }}
    />
  );
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  disabled,
  label
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ value: T; label: string; disabled?: boolean }>;
  disabled?: boolean;
  /** Accessible name when the select has no visible <label>. */
  label?: string;
}) {
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value as T)} disabled={disabled} aria-label={label}>
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ value: T; label: string; disabled?: boolean; title?: string }>;
  /** Accessible name of the group. Do not wrap a Segmented in a <label> (Field): use FieldGroup. */
  label?: string;
}) {
  const enabled = options.filter((o) => !o.disabled);
  const active = enabled.some((o) => o.value === value) ? value : enabled[0]?.value;
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          tabIndex={o.value === active ? 0 : -1}
          aria-checked={value === o.value}
          className={value === o.value ? "segmented__opt segmented__opt--on" : "segmented__opt"}
          onClick={() => onChange(o.value)}
          onKeyDown={(e) => {
            const index = enabled.findIndex((item) => item.value === o.value);
            const next = e.key === "Home" ? 0 : e.key === "End" ? enabled.length - 1
              : ["ArrowRight", "ArrowDown"].includes(e.key) ? (index + 1) % enabled.length
              : ["ArrowLeft", "ArrowUp"].includes(e.key) ? (index - 1 + enabled.length) % enabled.length : -1;
            if (next < 0 || !enabled[next]) return;
            e.preventDefault(); onChange(enabled[next].value);
            e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')[next]?.focus();
          }}
          disabled={o.disabled}
          title={o.title}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Check({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; disabled?: boolean }) {
  const id = useId();
  return (
    <label className="check" htmlFor={id}>
      <input id={id} type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

export function StatusDot({ state }: { state: "pass" | "fail" | "warn" | "unavailable" | "draft" | "valid" | "blocked" | "none" }) {
  return <span className={`dot dot--${state}`} aria-hidden />;
}

export function Paid({ what }: { what?: string }) {
  return (
    <span className="paid" title={what ? `${what} is part of the paid edition` : "Paid edition"}>
      Pro
    </span>
  );
}

export function Kv({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div className="kv__row" key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function fmt(v: number | null | undefined, digits = 1, unit = ""): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}${unit ? ` ${unit}` : ""}`;
}
