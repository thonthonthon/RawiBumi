/**
 * The only icon set is Tabler (MIT). PV-specific glyphs are drawn in-house on
 * Tabler's 24 px grid (from F3). Import icons from here so size and stroke
 * stay consistent.
 */
import {
  IconAlertTriangle,
  IconTrash,
  IconCircleCheck,
  IconCircleX,
  IconEye,
  IconEyeOff,
  IconInfoCircle,
  IconLayoutSidebarLeftCollapse,
  IconLayoutSidebarLeftExpand,
  IconLayoutSidebarRightCollapse,
  IconLayoutSidebarRightExpand,
  IconLock,
  IconLockOpen,
  IconMaximize,
  IconMinimize
} from "@tabler/icons-react";
import type { ComponentProps, ComponentType } from "react";

type TablerIcon = ComponentType<ComponentProps<typeof IconEye>>;

const make = (Icon: TablerIcon, size = 14) =>
  function Glyph(props: { title?: string; className?: string }) {
    return <Icon size={size} stroke={1.75} aria-hidden={props.title ? undefined : true} className={props.className} />;
  };

export const Eye = make(IconEye);
export const EyeOff = make(IconEyeOff);
export const Lock = make(IconLock);
export const Unlock = make(IconLockOpen);
export const Trash = make(IconTrash);

/** Pane controls (F1.1). */
export const PaneLeftCollapse = make(IconLayoutSidebarLeftCollapse, 16);
export const PaneLeftExpand = make(IconLayoutSidebarLeftExpand, 16);
export const PaneRightCollapse = make(IconLayoutSidebarRightCollapse, 16);
export const PaneRightExpand = make(IconLayoutSidebarRightExpand, 16);
export const FocusOn = make(IconMaximize, 16);
export const FocusOff = make(IconMinimize, 16);

/** Status glyphs: always shown with text, never colour alone (DESIGN.md §2). */
export const GlyphValid = make(IconCircleCheck, 14);
export const GlyphWarning = make(IconAlertTriangle, 14);
export const GlyphBlocked = make(IconCircleX, 14);
export const GlyphInfo = make(IconInfoCircle, 14);
