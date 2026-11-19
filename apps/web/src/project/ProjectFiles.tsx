import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "../client";
import { useActions } from "../state/store";
import { ApiError, type ProjectBackup, type ProjectView } from "../types";
import { Button, Check } from "../ui/kit";
import { ModalDialog } from "../ui/ModalDialog";

const code = (error: unknown) => (error instanceof ApiError && error.detail && typeof error.detail === "object" && "code" in error.detail ? String(error.detail.code) : null);

/** DATA1: import a .rawibumi file. The project keeps its ID; an existing one is replaced only after confirmation. */
export function ImportProjectButton({ disabled, onImported }: { disabled?: boolean; onImported: (view: ProjectView) => void }) {
  const { t } = useTranslation();
  const { run, toast } = useActions();
  const input = useRef<HTMLInputElement>(null);
  const [clash, setClash] = useState<{ file: File; message: string } | null>(null);
  async function load(file: File, replace: boolean) {
    const view = await run(t("data1.importing"), async () => {
      try { return await engine.importProject(file, file.name, replace); }
      catch (error) {
        if (code(error) === "project_exists") { setClash({ file, message: (error as ApiError).message }); return undefined; }
        throw error;
      }
    });
    if (view) { setClash(null); toast("ok", t("data1.imported", { name: view.bundle.project.name })); onImported(view); }
  }
  return (
    <>
      <input ref={input} type="file" accept=".rawibumi,application/zip" hidden data-import-project
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void load(f, false); }} />
      <Button small disabled={disabled} onClick={() => input.current?.click()}>{t("data1.import")}</Button>
      {clash && (
        <ModalDialog alert small label={t("data1.clashTitle")} onClose={() => setClash(null)}>
          <header className="modal__head"><h2>{t("data1.clashTitle")}</h2></header>
          <div className="modal__body">
            <p>{clash.message}</p>
            <p>{t("data1.clashNote")}</p>
            <div className="row">
              <Button cancel onClick={() => setClash(null)}>{t("data1.cancel")}</Button>
              <Button tone="danger" onClick={() => void load(clash.file, true)}>{t("data1.replace")}</Button>
            </div>
          </div>
        </ModalDialog>
      )}
    </>
  );
}

/** DATA1: download the project as one file; saved results are included unless unticked. */
export function ExportProjectDialog({ projectId, name, onClose }: { projectId: string; name: string; onClose: () => void }) {
  const { t } = useTranslation();
  const { run } = useActions();
  const [results, setResults] = useState(true);
  async function download() {
    const file = await run(t("data1.exporting"), () => engine.exportProject(projectId, results));
    if (!file) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(file.blob);
    a.download = file.filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
    onClose();
  }
  return (
    <ModalDialog small label={t("data1.exportTitle", { name })} onClose={onClose}>
      <header className="modal__head"><h2>{t("data1.exportTitle", { name })}</h2></header>
      <div className="modal__body" data-export-project>
        <p>{t("data1.exportNote")}</p>
        <Check checked={results} onChange={setResults} label={t("data1.includeResults")} />
        <p className="note">{t(results ? "data1.withResults" : "data1.withoutResults")}</p>
        <div className="row">
          <Button cancel onClick={onClose}>{t("data1.cancel")}</Button>
          <Button tone="primary" onClick={() => void download()}>{t("data1.download")}</Button>
        </div>
      </div>
    </ModalDialog>
  );
}

/** DATA1: the project's backups, newest first (the newest is the current save); restoring is confirmed. */
export function BackupsDialog({ projectId, name, onClose, onRestored }: { projectId: string; name: string; onClose: () => void; onRestored: (view: ProjectView) => void }) {
  const { t } = useTranslation();
  const { run } = useActions();
  const [rows, setRows] = useState<ProjectBackup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ProjectBackup | null>(null);
  useEffect(() => {
    engine.projectBackups(projectId).then(setRows).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [projectId]);
  const when = (stamp: string) => `${stamp.slice(0, 4)}-${stamp.slice(4, 6)}-${stamp.slice(6, 8)} ${stamp.slice(9, 11)}:${stamp.slice(11, 13)}:${stamp.slice(13, 15)} UTC`;
  async function restore(row: ProjectBackup) {
    const view = await run(t("data1.restoring"), () => engine.restoreBackup(projectId, row.backup_id));
    if (view) { onRestored(view); onClose(); }
  }
  return (
    <ModalDialog label={t("data1.backupsTitle", { name })} onClose={onClose}>
      <header className="modal__head"><h2>{t("data1.backupsTitle", { name })}</h2></header>
      <div className="modal__body" data-backups>
        <p className="note">{t("data1.backupsNote")}</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        {!rows && !error && <p role="status">{t("data1.loading")}</p>}
        {rows && !rows.length && <p>{t("data1.noBackups")}</p>}
        {rows && rows.length > 0 && (
          <table className="tbl tbl--dense">
            <thead><tr><th>{t("data1.savedAt")}</th><th className="num">{t("data1.revision")}</th><th>{t("data1.kind")}</th><th /></tr></thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.backup_id} data-backup={row.backup_id}>
                  <td>{when(row.saved_at)}{i === 0 && !row.protected ? ` · ${t("data1.current")}` : ""}</td>
                  <td className="num">{row.revision_number ?? "—"}</td>
                  <td>{row.protected ? t(`data1.protected_${row.reason}`, { defaultValue: row.reason ?? "" }) : t("data1.rolling")}</td>
                  <td><Button small onClick={() => setConfirm(row)}>{t("data1.restore")}</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {confirm && (
          <div className="issue issue--draft" role="alert">
            <p>{t("data1.restoreConfirm", { when: when(confirm.saved_at) })}</p>
            <div className="row"><Button cancel onClick={() => setConfirm(null)}>{t("data1.cancel")}</Button>
              <Button tone="primary" onClick={() => void restore(confirm)}>{t("data1.restore")}</Button></div>
          </div>
        )}
        <div className="row"><Button cancel onClick={onClose}>{t("data1.close")}</Button></div>
      </div>
    </ModalDialog>
  );
}
