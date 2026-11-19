import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Check, Field } from "../ui/kit";
import { ModalDialog } from "../ui/ModalDialog";
import { loadKey, loadProvider, providerReady, saveKey, saveProvider, templateProblem, type ImageryProvider } from "./provider";

/** The custom provider and whether it can be shown now; re-renders when the settings change in any view. */
export function useImageryProvider(): { provider: ImageryProvider | null; key: string; ready: boolean } {
  const read = () => { const provider = loadProvider(), key = loadKey(); return { provider, key, ready: providerReady(provider, key) }; };
  const [value, setValue] = useState(read);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const update = () => setValue(read());
    window.addEventListener("rawibumi:imagery-provider", update);
    window.addEventListener("storage", update);
    return () => { window.removeEventListener("rawibumi:imagery-provider", update); window.removeEventListener("storage", update); };
  }, []);
  return value ?? read();
}

/** Ask the settings dialog (mounted once per screen) to open. */
export const openProviderSettings = () => window.dispatchEvent(new Event("rawibumi:imagery-provider-settings"));

/** Settings for the bring-your-own-key provider (DEC-U2). The key stays in this browser only. */
export function ProviderDialogHost() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener("rawibumi:imagery-provider-settings", show);
    return () => window.removeEventListener("rawibumi:imagery-provider-settings", show);
  }, []);
  return open ? <ProviderDialog onClose={() => setOpen(false)} /> : null;
}

function ProviderDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const saved = loadProvider();
  const [name, setName] = useState(saved?.name ?? "");
  const [template, setTemplate] = useState(saved?.tileUrlTemplate ?? "");
  const [attribution, setAttribution] = useState(saved?.attribution ?? "");
  const [key, setKey] = useState(loadKey());
  const [terms, setTerms] = useState(saved?.termsAccepted ?? false);
  const problem = template ? templateProblem(template) : "imagery.needsTemplate";
  const blocked = problem ?? (!attribution.trim() ? "imagery.needsAttribution" : !terms ? "imagery.needsTerms" : null);
  return (
    <ModalDialog label={t("imagery.providerTitle")} onClose={onClose}>
      <header className="modal__head"><h2>{t("imagery.providerTitle")}</h2></header>
      <div className="modal__body" data-imagery-provider>
        <p className="note">{t("imagery.providerNote")}</p>
        <Field label={t("imagery.providerName")}><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("imagery.providerNamePlaceholder")} /></Field>
        <Field label={t("imagery.template")} hint={t("imagery.templateHint")}>
          <input className="input" value={template} onChange={(e) => setTemplate(e.target.value.trim())} placeholder="https://…/{z}/{x}/{y}.jpg?key={key}" aria-invalid={!!template && !!problem} spellCheck={false} />
        </Field>
        {template && problem && <p className="form-error" role="alert">{t(problem)}</p>}
        <Field label={t("imagery.key")} hint={t("imagery.keyHint")}><input className="input" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} /></Field>
        <Field label={t("imagery.attribution")}><input className="input" value={attribution} onChange={(e) => setAttribution(e.target.value)} /></Field>
        <Check checked={terms} onChange={setTerms} label={t("imagery.terms")} />
        <div className="row">
          <Button cancel onClick={onClose}>{t("imagery.cancel")}</Button>
          {saved && <Button tone="danger" onClick={() => { saveProvider(null); saveKey(""); onClose(); }}>{t("imagery.remove")}</Button>}
          <Button tone="primary" disabled={!!blocked} title={blocked ? t(blocked) : undefined}
            onClick={() => { saveProvider({ name: name.trim() || t("imagery.defaultName"), tileUrlTemplate: template, attribution: attribution.trim(), termsAccepted: terms }); saveKey(key); onClose(); }}>
            {t("imagery.save")}
          </Button>
        </div>
      </div>
    </ModalDialog>
  );
}
