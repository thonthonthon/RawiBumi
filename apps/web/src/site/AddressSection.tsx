import { useTranslation } from "react-i18next";
import { useStore } from "../state/store";
import { Button, Field } from "../ui/kit";
import { useSiteAddress } from "./useSiteAddress";

/** Site panel: the site address for the report cover (F7.1). Looked up from the coordinates, editable. */
export function AddressSection() {
  const { t, i18n } = useTranslation();
  const { state } = useStore();
  const v = state.view!;
  const site = v.bundle.project.site;
  const a = useSiteAddress(v.bundle.project.project_id, site.latitude_deg, site.longitude_deg, i18n.language);
  const looking = a.status === "looking";

  let note: string | null = null;
  if (looking) note = t("site.looking");
  else if (a.status === "failed") note = t("site.failed", { error: a.error ?? "" });
  else if (a.address?.source === "lookup") note = t("site.fromLookup", { service: a.serviceLabel ?? "", attribution: a.address.attribution ?? "" });
  else if (a.address?.source === "user") note = t("site.edited");
  else if (!a.available) note = t("site.unavailable");

  return (
    <>
      <Field label={t("site.addressLabel")} hint={t("site.addressHint")}>
        <textarea className="input" rows={3} value={a.address?.text ?? ""} placeholder={looking ? t("site.looking") : ""} onChange={(e) => a.setText(e.target.value)} data-site-address />
      </Field>
      {note && (
        <p className={a.status === "failed" ? "note note--warn" : "note"} role={a.status === "failed" ? "alert" : "status"} data-address-status={a.status}>
          {note}
        </p>
      )}
      {a.available && (
        <div className="row">
          <Button onClick={a.lookupNow} disabled={looking || !a.allowed}>
            {t("site.lookupAgain")}
          </Button>
          <label className="check">
            <input type="checkbox" checked={a.allowed} onChange={(e) => a.setAllowed(e.target.checked)} />
            {t("site.allowLookup")}
          </label>
        </div>
      )}
      {a.available && <p className="note">{t("site.allowLookupNote", { service: a.serviceLabel ?? "" })}</p>}
      <p className="note">{t("site.storedLocally")}</p>
    </>
  );
}
