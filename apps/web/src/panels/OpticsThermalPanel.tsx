import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "../client";
import { useStore } from "../state/store";
import { formatNumber } from "../formatNumbers";
import type { OpticsThermalPatch, OpticsThermalValues, ResolvedOpticsThermalSettings, SimulationRunRecord, TranspositionChoice } from "../types";
import { Button, Field } from "../ui/kit";

export type OpticsDraft = Record<string, string>;
export function opticsDraft(settings: ResolvedOpticsThermalSettings): OpticsDraft {
  const v=settings.values;
  return { transposition:v.transposition, iam:v.iam.selection, preset:v.thermal.mounting_preset,
    uc:formatNumber(v.thermal.u_c_w_m2k), uv:formatNumber(v.thermal.u_v_w_m2k_per_ms), basis:v.thermal.irradiance_basis,
    ...Object.fromEntries(v.albedo.monthly_values.map((value,i)=>[`month${i+1}`,formatNumber(value)])) };
}
export function opticsErrors(draft: OpticsDraft): string[] {
  const errors:string[]=[];
  for (const k of ["uc","uv",...Array.from({length:12},(_,i)=>`month${i+1}`)]) {
    const n=draft[k]?.trim() ? Number(draft[k]) : NaN;
    if (!Number.isFinite(n) || (k==="uc" ? n<=0 : n<0) || k.startsWith("month") && n>1) errors.push(k);
  }
  return errors;
}
export function opticsPatch(initial: OpticsDraft, draft: OpticsDraft): OpticsThermalPatch {
  const overrides: Extract<OpticsThermalPatch,{overrides:unknown}>["overrides"]={};
  if(draft.transposition!==initial.transposition) overrides.transposition=draft.transposition as TranspositionChoice;
  if(draft.iam!==initial.iam) overrides.iam={selection:draft.iam as OpticsThermalValues["iam"]["selection"]};
  const thermal: NonNullable<typeof overrides.thermal> = {};
  if (draft.preset !== initial.preset && draft.preset !== "custom") {
    thermal.mounting_preset = draft.preset as OpticsThermalValues["thermal"]["mounting_preset"];
  } else if (["preset", "uc", "uv"].some(k => draft[k] !== initial[k])) {
    thermal.mounting_preset = "custom";
    thermal.u_c_w_m2k = Number(draft.uc);
    thermal.u_v_w_m2k_per_ms = Number(draft.uv);
  }
  if (draft.basis !== initial.basis) thermal.irradiance_basis = draft.basis as OpticsThermalValues["thermal"]["irradiance_basis"];
  if (Object.keys(thermal).length) overrides.thermal = thermal;
  if(Array.from({length:12},(_,i)=>`month${i+1}`).some(k=>draft[k]!==initial[k])) overrides.albedo={monthly_values:Array.from({length:12},(_,i)=>Number(draft[`month${i+1}`]))};
  return {overrides};
}
export function OpticsThermalPanel({defaults}:{defaults?:ResolvedOpticsThermalSettings}) {
  const {state,dispatch,run}=useStore(); const {t}=useTranslation();const view=state.view!;
  const settings=view.resolved_optics_thermal_settings??defaults;
  const [draft,setDraft]=useState<OpticsDraft>(()=>settings?opticsDraft(settings):{});
  const [annual,setAnnual]=useState("");
  useEffect(()=>{setDraft(settings?opticsDraft(settings):{});setAnnual("");},[settings,view.bundle.project.project_id]);
  if(!settings)return <p role="status">{t("s7d.defaultsUnavailable")}</p>;
  const initial=opticsDraft(settings),errors=opticsErrors(draft),busy=!!state.busy;
  const changed=JSON.stringify(initial)!==JSON.stringify(draft);
  async function save(patch:OpticsThermalPatch){if(busy)return;const next=await run(t("optics.saving"),()=>engine.updateOpticsThermal(view.bundle.project.project_id,patch));if(next)dispatch({type:"setView",view:next});}
  const select=(key:string,label:string,choices:string[]) => <Field key={key} label={label}><select className="input" aria-label={label} value={draft[key]??""} disabled={busy} onChange={e=>{
    const value=e.target.value,next={...draft,[key]:value};
    if(key==="preset"&&value!=="custom"){next.uc=String(({semi_integrated:20,open_rack:29,insulated_back:15,dome:27} as Record<string,number>)[value]);next.uv="0";}
    setDraft(next);
  }}>{choices.map(value=><option key={value} value={value}>{t(`optics.${key}_${value}`)}</option>)}</select></Field>;
  return <div className="stack" data-optics-settings={settings.status}>
    <h3>{t("optics.title")}</h3><p>{t(settings.status==="edited"?"losses.edited":"losses.recommended")} · {settings.defaults_id}</p>
    {select("transposition",t("optics.transposition"),["perez_hourly","perez_1990","perez_driesse","hay_davies","isotropic"])}
    {select("iam",t("optics.iam"),["module_auto","module_table","physical_glass","none"])}
    <p className="note">{t("optics.fallback")}</p>
    {select("preset",t("optics.mounting"),["semi_integrated","open_rack","insulated_back","dome","custom"])}
    <div className="grid2">{["uc","uv"].map(key=><Field key={key} label={t(`optics.${key}`)}><input className="input" type="number" step="any" disabled={busy} aria-invalid={errors.includes(key)} value={draft[key]??""} onChange={e=>setDraft({...draft,[key]:e.target.value,preset:"custom"})}/></Field>)}</div>
    {select("basis",t("optics.basis"),["effective","incident_pre_iam"])}<p className="note">{t("optics.basisHint")}</p>
    <p className="note">{t("optics.absorption")}</p>
    <Field label={t("optics.annual")}><input className="input" type="number" step="any" min="0" max="1" disabled={busy} value={annual} onChange={e=>setAnnual(e.target.value)}/></Field>
    <Button disabled={busy||!annual.trim()||!Number.isFinite(Number(annual))||Number(annual)<0||Number(annual)>1} onClick={()=>setDraft({...draft,...Object.fromEntries(Array.from({length:12},(_,i)=>[`month${i+1}`,annual]))})}>{t("optics.applyAnnual")}</Button>
    <div className="grid2">{Array.from({length:12},(_,i)=>`month${i+1}`).map((key,i)=><Field key={key} label={t("optics.month",{month:i+1})}><input className="input" type="number" step="any" min="0" max="1" disabled={busy} aria-invalid={errors.includes(key)} value={draft[key]??""} onChange={e=>setDraft({...draft,[key]:e.target.value})}/></Field>)}</div>
    <p className="note">{t("optics.localMonth")}</p>
    {errors.length>0&&<p role="alert">{t("optics.invalid",{fields:errors.map(k=>k.startsWith("month")?t("optics.month",{month:k.slice(5)}):t(`optics.${k}`)).join(", ")})}</p>}
    <div className="row"><Button disabled={busy||!changed||errors.length>0} onClick={()=>void save(opticsPatch(initial,draft))}>{t("optics.save")}</Button><Button disabled={busy||settings.status!=="edited"} onClick={()=>void save({reset_to_recommended_defaults:true})}>{t("optics.reset")}</Button></div>
  </div>;
}

/** Read only the selected run, never substitute the current project's choices. */
export function RunOpticsThermalSettings({run}:{run:SimulationRunRecord}) {
  const {t}=useTranslation();const s=run.resolved_optics_thermal_settings;
  if(!s)return <p>{t("optics.legacy")}</p>;
  const v=s.values;
  return <details data-run-optics-settings={s.settings_sha256}><summary>{t("optics.runSettings")} · {t(s.status==="edited"?"losses.edited":"losses.recommended")}</summary>
    <p>{s.defaults_id} · {s.settings_sha256}</p><dl>
      <dt>{t("optics.transposition")}</dt><dd>{t(`optics.transposition_${v.transposition}`)}</dd>
      <dt>{t("optics.iam")}</dt><dd>{t(`optics.iam_${v.iam.selection}`)}</dd>
      <dt>{t("optics.uc")}</dt><dd>{formatNumber(v.thermal.u_c_w_m2k)}</dd>
      <dt>{t("optics.uv")}</dt><dd>{formatNumber(v.thermal.u_v_w_m2k_per_ms)}</dd>
      <dt>{t("optics.basis")}</dt><dd>{t(`optics.basis_${v.thermal.irradiance_basis}`)}</dd>
      {v.albedo.monthly_values.map((n,i)=><div key={i}><dt>{t("optics.month",{month:i+1})}</dt><dd>{formatNumber(n)}</dd></div>)}
      {Object.entries(s.modules??{}).map(([id,m])=><div key={id}><dt>{id} · {m.module_revision_id}</dt><dd>{t(`optics.source_${m.iam_source}`)} · α {formatNumber(m.alpha_absorption)}</dd></div>)}
    </dl>
  </details>;
}
