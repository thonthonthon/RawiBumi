import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { keyParts } from "../commands/keys";
import { PaneLeftCollapse, PaneLeftExpand, PaneRightCollapse, PaneRightExpand } from "../ui/icons";

interface PaneProps {
  /** Pane name, used in the header and in the button labels. */
  title: string;
  side: "left" | "right";
  collapsed: boolean;
  onToggle: () => void;
  /** tinykeys key string of the toggle command, shown in the tooltip. */
  keys: string;
  children: ReactNode;
}

/**
 * A side pane around the stage: a header with a collapse button, or, when
 * collapsed, a 32 px strip whose whole height expands it again (F1.1).
 */
export function Pane({ title, side, collapsed, onToggle, keys, children }: PaneProps) {
  const { t } = useTranslation();
  const shortcut = keyParts(keys).join("+");
  if (collapsed) {
    const Icon = side === "left" ? PaneLeftExpand : PaneRightExpand;
    return (
      <button type="button" className="panestrip" onClick={onToggle} aria-label={t("panes.expand", { pane: title })} title={`${t("panes.expand", { pane: title })} · ${shortcut}`}>
        <Icon />
        <span className="panestrip__label" aria-hidden="true">
          {title}
        </span>
      </button>
    );
  }
  const Icon = side === "left" ? PaneLeftCollapse : PaneRightCollapse;
  return (
    <div className="pane">
      <div className="pane__head">
        <h2 className="pane__title">{title}</h2>
        <button type="button" className="iconbtn" onClick={onToggle} aria-label={t("panes.collapse", { pane: title })} title={`${t("panes.collapse", { pane: title })} · ${shortcut}`}>
          <Icon />
        </button>
      </div>
      <div className="pane__body">{children}</div>
    </div>
  );
}
