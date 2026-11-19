import { ReactNode, useId, useState } from "react";
import { PENDING } from "../pending";

export function Button({
  children,
  onClick,
  disabled,
  tone = "default",
  title,
  type = "button",
  small
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "default" | "primary" | "ghost" | "danger";
  title?: string;
  type?: "button" | "submit";
  small?: boolean;
}) {
  return (
    <button type={type} className={`btn btn--${tone}${small ? " btn--sm" : ""}`} onClick={onClick} disabled={disabled} title={title}>
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

export function Section({ title, children, aside, defaultOpen = true }: { title: string; children: ReactNode; aside?: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className={open ? "section" : "section section--closed"}>
      <header className="section__head">
        <button type="button" className="section__toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
          <span className="section__chev" aria-hidden>
            {open ? "▾" : "▸"}
          </span>
          {title}
        </button>
        {aside}
      </header>
      {open && <div className="section__body">{children}</div>}
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

export function NumberInput({
  value,
  onChange,
  step = 0.1,
  min,
  max,
  disabled
}: {
  value: number;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  max?: number;
  disabled?: boolean;
}) {
  const [text, setText] = useState<string | null>(null);
  return (
    <input
      className="input input--num"
      type="number"
      value={text ?? (Number.isFinite(value) ? String(Math.round(value * 1e6) / 1e6) : "")}
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
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  disabled
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ value: T; label: string; disabled?: boolean }>;
  disabled?: boolean;
}) {
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value as T)} disabled={disabled}>
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
  options
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ value: T; label: string; disabled?: boolean; title?: string }>;
}) {
  return (
    <div className="segmented" role="radiogroup">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          className={value === o.value ? "segmented__opt segmented__opt--on" : "segmented__opt"}
          onClick={() => onChange(o.value)}
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
