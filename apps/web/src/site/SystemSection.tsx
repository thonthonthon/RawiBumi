import { useState } from "react";
import { useTranslation } from "react-i18next";
import { dcCapacityKwp } from "../results/model";
import { useStore } from "../state/store";
import { Field, Kv, Section, Select } from "../ui/kit";
import { beyondSimulation, formatPvCapacity, INSTALLATION_TYPES, useSystemInfo, type InstallationType } from "./systemInfo";

/** A number field that may be left empty (null). Negative or unreadable input is not stored. */
function OptionalNumber({ value, onChange, label }: { value: number | null; onChange: (v: number | null) => void; label: string }) {
  const [text, setText] = useState<string | null>(null);
  return (
    <input
      className="input input--num"
      type="number"
      min={0}
      step="any"
      aria-label={label}
      value={text ?? (value === null ? "" : String(value))}
      onChange={(e) => {
        const raw = e.target.value;
        setText(raw);
        if (raw.trim() === "") onChange(null);
        else {
          const v = Number(raw);
          if (Number.isFinite(v) && v >= 0) onChange(v);
        }
      }}
      onBlur={() => setText(null)}
    />
  );
}

/** Site panel: installation type, PV capacity (from the design) and BESS capacity, for the report cover (F7.2). */
export function SystemSection() {
  const { t } = useTranslation();
  const { state } = useStore();
  const v = state.view!;
  const [s, set] = useSystemInfo(v.bundle.project.project_id);
  return (
    <Section title={t("sections.installation")}>
      <Field label={t("site.installationType")}>
        <Select<InstallationType | "">
          value={s.installationType ?? ""}
          onChange={(x) => set({ installationType: x === "" ? null : x })}
          options={[{ value: "", label: t("site.type_none") }, ...INSTALLATION_TYPES.map((x) => ({ value: x, label: t(`site.type_${x}`) }))]}
        />
      </Field>
      <Kv rows={[[t("site.pvCapacity"), <span key="pv" data-pv-capacity>{formatPvCapacity(dcCapacityKwp(v))}</span>]]} />
      <div className="grid2">
        <Field label={t("site.bessEnergy")} unit="kWh">
          <OptionalNumber value={s.bessEnergyKwh} onChange={(x) => set({ bessEnergyKwh: x })} label={t("site.bessEnergy")} />
        </Field>
        <Field label={t("site.bessPower")} unit="kW">
          <OptionalNumber value={s.bessPowerKw} onChange={(x) => set({ bessPowerKw: x })} label={t("site.bessPower")} />
        </Field>
      </div>
      <p className="note">{t("site.bessHint")}</p>
      <p className={beyondSimulation(s) ? "note note--warn" : "note"} data-system-note>
        {t("site.systemNote")}
      </p>
    </Section>
  );
}
