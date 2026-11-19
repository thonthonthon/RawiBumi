import { Command as Cmdk } from "cmdk";
import { useTranslation } from "react-i18next";
import { track } from "../platform/telemetry";
import { keyParts } from "./keys";
import type { Command, CommandGroup } from "./useCommands";

const GROUPS: Array<[CommandGroup, string]> = [
  ["navigate", "commands.groupNavigate"],
  ["project", "commands.groupProject"],
  ["view", "commands.groupView"],
  ["preferences", "commands.groupPreferences"]
];

export function Keys({ keys }: { keys: string }) {
  return (
    <span className="keys">
      {keyParts(keys).map((k, i) => (
        <kbd key={i}>{k}</kbd>
      ))}
    </span>
  );
}

export function CommandPalette({ open, onOpenChange, commands }: { open: boolean; onOpenChange: (open: boolean) => void; commands: Command[] }) {
  const { t } = useTranslation();
  return (
    <Cmdk.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label={t("commands.palette")}
      overlayClassName="palette-overlay"
      contentClassName="palette"
    >
      <Cmdk.Input placeholder={t("commands.placeholder")} className="palette__input" />
      <Cmdk.List className="palette__list">
        <Cmdk.Empty className="palette__empty">{t("commands.empty")}</Cmdk.Empty>
        {GROUPS.map(([group, key]) => {
          const items = commands.filter((c) => c.group === group && c.id !== "view.palette");
          if (!items.length) return null;
          return (
            <Cmdk.Group key={group} heading={t(key)} className="palette__group">
              {items.map((c) => (
                <Cmdk.Item
                  key={c.id}
                  value={`${c.label} ${c.id}`}
                  disabled={c.disabled}
                  className="palette__item"
                  onSelect={() => {
                    onOpenChange(false);
                    c.run();
                    track("command.run", { id: c.id, via: "palette" });
                  }}
                >
                  <span>{c.label}</span>
                  {c.keys && <Keys keys={c.keys} />}
                  {c.alternativeKeys?.map((keys) => <Keys key={keys} keys={keys} />)}
                </Cmdk.Item>
              ))}
            </Cmdk.Group>
          );
        })}
      </Cmdk.List>
    </Cmdk.Dialog>
  );
}
