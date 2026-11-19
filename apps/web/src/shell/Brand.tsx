import { useTranslation } from "react-i18next";

/** Placeholder mark (four-tile diamond in the logo palette) until the designer's mark arrives. */
export function Mark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" className="mark">
      <g transform="rotate(45 20 20)">
        <rect x="7" y="7" width="12" height="12" style={{ fill: "var(--rb-color-sun-300)" }} />
        <rect x="21" y="7" width="12" height="12" style={{ fill: "var(--rb-color-sun-400)" }} />
        <rect x="7" y="21" width="12" height="12" style={{ fill: "var(--rb-color-sun-500)" }} />
        <rect x="21" y="21" width="12" height="12" style={{ fill: "var(--rb-color-sun-700)" }} />
      </g>
    </svg>
  );
}

export function Brand({ withBy = false }: { withBy?: boolean }) {
  const { t } = useTranslation();
  return (
    <span className="brandmark">
      <Mark />
      <span className="brandmark__word" translate="no">
        RAWIBUMI
      </span>
      {withBy && <span className="brandmark__by">{t("app.by")}</span>}
    </span>
  );
}
