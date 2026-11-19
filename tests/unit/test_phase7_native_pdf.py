"""Full-report, worker isolation and process-limit regressions."""

from copy import deepcopy
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pandas as pd
import pytest

from engine.simulation.artifacts import canonical_json_bytes
from reporting.exports import native_pdf as pdf
from tests.unit.test_phase7_csv_export import persisted
from tests.unit.test_phase7_report_contract import report_case, context, save_registration

WORKER_PAGE_CAP = int(re.search(r"const MAX_PAGES = (\d+);", pdf.WORKER.read_text()).group(1))


def seal(envelope):
    envelope.pop("snapshot_sha256", None)
    envelope["snapshot_sha256"] = sha256(canonical_json_bytes(envelope)).hexdigest()
    return envelope


def snapshot(directory):
    return {p.relative_to(directory): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in directory.rglob("*") if p.is_file()}


def node_binary():
    value = os.environ.get("RAWIBUMI_PDF_NODE") or shutil.which("node")
    assert value and Path(value).is_absolute(), "Configure RAWIBUMI_PDF_NODE for fixed-HTML tests"
    return value


def worker_html(projection):
    script = "const fs=require('node:fs');process.stdout.write(require(process.argv[1]).reportHTML(JSON.parse(fs.readFileSync(0,'utf8'))));"
    root=Path(__file__).resolve().parents[2]/'apps/web'
    completed=subprocess.run([node_binary(),"--max-old-space-size=128","-e",script,str(pdf.WORKER)],input=canonical_json_bytes(projection),capture_output=True,timeout=10,env={"PATH":"/usr/bin:/bin","RAWIBUMI_PDF_RUNTIME_ROOT":str(root)})
    assert completed.returncode==0,completed.stderr.decode()
    assert not completed.stderr
    return completed.stdout.decode('utf-8')


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags, self.attrs, self.content = [], [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)

    def handle_data(self, data):
        self.content.append(data)


def test_locale_changes_presentation_only_and_digest_is_recomputed(report_case, monkeypatch):
    case=report_case();before=snapshot(case.directory);source=context(case)
    p_en=pdf.prepare_snapshot(source,locale='en');p_id=pdf.prepare_snapshot(source,locale='id')
    assert {k:v for k,v in p_en.items() if k!='locale'}=={k:v for k,v in p_id.items() if k!='locale'}
    assert 'Reference Production' in worker_html(p_en) and 'Produksi Referensi' in worker_html(p_id)
    source['summary']['total_energy_wh']+=1
    monkeypatch.setattr(pdf,'_run_worker',lambda *args:pytest.fail('worker called before integrity check'))
    with pytest.raises(pdf.NativePDFError,match='digest mismatch'):pdf.render_native_pdf(source)
    assert snapshot(case.directory)==before


def test_service_verifies_first_and_does_not_accept_forged_context(report_case, monkeypatch):
    case=report_case();expected=context(case);calls=[];original=case.study.report_snapshot
    def verified(*args):calls.append('verified');return original(*args)
    def render(value,**kwargs):
        assert calls==['verified'] and value==expected and kwargs['locale']=='id'
        calls.append('renderer');return b'synthetic renderer sentinel'
    monkeypatch.setattr(case.study,'report_snapshot',verified);monkeypatch.setattr(pdf,'render_native_pdf',render)
    monkeypatch.setattr(case.study,'run_result',lambda *args:pytest.fail('mutable result path used'))
    assert case.study.native_pdf_document(case.project_id,case.run_id,locale='id')==b'synthetic renderer sentinel'
    assert calls==['verified','renderer']
    with pytest.raises(TypeError):case.study.native_pdf_document(case.project_id,case.run_id,context=expected)


def test_service_membership_and_saved_identity_cannot_be_bypassed(report_case, monkeypatch):
    case, other = report_case(), report_case()
    monkeypatch.setattr(pdf, "render_native_pdf", lambda *a: pytest.fail("Unverified context reached renderer"))
    projects = case.app.state.project_service
    bundle = projects.get_bundle(case.project_id)
    foreign = other.app.state.project_service.get_bundle(other.project_id)["simulation_runs"][0]
    for records in ([], [foreign]):
        bundle["simulation_runs"] = records
        projects.save_bundle(bundle)
        with pytest.raises(ValueError):
            case.study.native_pdf_document(case.project_id, case.run_id)
    case = report_case()
    save_registration(case, lambda r: r.__setitem__("input_hash", "b" * 64))
    with pytest.raises(ValueError):
        case.study.native_pdf_document(case.project_id, case.run_id)


@pytest.mark.parametrize("hours", [3, 168])
@pytest.mark.parametrize("locale", ["en", "id"])
def test_partial_period_and_monthly_figures_are_source_only(report_case, hours, locale):
    frame=pd.DataFrame({'timestamp':pd.date_range('2026-10-01T10:00:00+07:00',periods=hours,freq='h'),'interval_seconds':3600.,'pcc_power_w':5.,'interval_energy_wh':5.})
    source=context(report_case(frame=frame));payload=pdf.prepare_snapshot(source,locale=locale)
    assert source['summary']['period_duration_hours']==hours
    assert source['summary']['total_energy_wh']==hours*5 and source['summary']['annual_energy_wh'] is None
    assert source['summary']['monthly_energy']==[{'month':'2026-10','energy_wh':hours*5}]
    html=worker_html(payload)
    assert ('simulated period' if locale=='en' else 'periode simulasi') in html
    assert ('not applicable to a partial period' if locale=='en' else 'tidak berlaku untuk periode parsial') in html
    assert source['summary']['period_start_time'] in html and source['summary']['period_end_time'] in html


@pytest.mark.parametrize("path,value", [
 (("schema",),"rawibumi.report_snapshot.v2"),
 (("identity","engine_version"),None), (("identity","project_id"),"x"*129),
 (("summary","total_energy_wh"),None), (("summary","performance_ratio"),True),
 (("summary","annual_energy_wh"),100.), (("summary","capacity_factor_basis"),"new_basis"),
 (("summary","monthly_energy"),[{"month":"2026-13","energy_wh":5}]),
 (("summary","monthly_energy"),[{"month":"0000-01","energy_wh":5}]),
 (("summary","monthly_energy"),[{"month":"2026-09","energy_wh":5}]),
 (("summary","monthly_energy"),[{"month":"2026-10","energy_wh":None}]),
 (("summary","monthly_energy"),[{"month":"2026-10","energy_wh":5}]*13),
 (("summary","monthly_energy"),[{"month":"2026-10","energy_wh":5}]*2),
 (("method","limits"),[{"code":"A","en":"A","id":"A"}]*2),
 (("method","limits"),None), (("provenance","source_dataset"),{"sha256":"z"*64}),
 (("summary","period_duration_hours"),8760),
 (("summary","period_start_time"),"2026-10-01T10:00:00"), (("hourly_ac","interval_seconds"),None),
])
def test_malformed_snapshot_rejected_without_silent_truncation(report_case, path, value):
    source=context(report_case());target=source
    for part in path[:-1]:target=target[part]
    target[path[-1]]=value
    with pytest.raises(pdf.NativePDFError):pdf.prepare_snapshot(seal(source))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_even_in_unprojected_hourly_data_rejected(report_case, value):
    source=context(report_case());source['hourly_ac']['values'][0][0]=value
    with pytest.raises(pdf.NativePDFError,match='nonfinite'):pdf.prepare_snapshot(source)


@pytest.mark.parametrize("locale", [None, [], "EN", "en-US", "fr"])
def test_locale_is_exact(report_case, locale):
    with pytest.raises(pdf.NativePDFError,match='locale'):pdf.prepare_snapshot(context(report_case()),locale=locale)


@pytest.mark.parametrize("key", ["summary", "hourly_ac", "identity", "provenance"])
def test_missing_sections_rejected(report_case, key):
    source=context(report_case());del source[key]
    with pytest.raises(pdf.NativePDFError):pdf.prepare_snapshot(seal(source))


def test_limits_and_unsafe_integer_refusal(report_case, monkeypatch):
    source=context(report_case());source['summary']['peak_dc_power_w']=9007199254740993
    with pytest.raises(pdf.NativePDFError,match='safe integer'):pdf.prepare_snapshot(seal(source))
    source=context(report_case());monkeypatch.setattr(pdf,'MAX_CONTEXT_BYTES',100)
    with pytest.raises(pdf.NativePDFError,match='size limit'):pdf.prepare_snapshot(source)
    source['site']['extra']='x'*(pdf.MAX_STRING_CHARS+1)
    with pytest.raises(pdf.NativePDFError,match='string limit'):pdf.prepare_snapshot(source)
    with pytest.raises(pdf.NativePDFError,match='list limit'):pdf._bound_tree([None]*(pdf.MAX_LIST_ITEMS+1))


@pytest.mark.parametrize("attack", ["<script>alert(1)</script>", '<img src="https://evil.invalid/x">',
    "https://evil.invalid", "file:///home/private/run", "/home/private/secret", r"C:\private\secret", "C:/private/secret",
    "javascript:alert", "s3:private", "urn:secret", "safe\u202eevil", "safe\u2066evil", "safe\x00evil"])
def test_hostile_identifiers_and_warnings_rejected(report_case, attack):
    source=context(report_case())
    for section,key in [('identity','project_id'),('provenance','source_timezone')]:
        changed=deepcopy(source);changed[section][key]=attack
        with pytest.raises(pdf.NativePDFError):pdf.prepare_snapshot(seal(changed))
    source['design_view']['bundle']['simulation_runs'][0]['assumptions']=[{'assumption_id':'test','severity':'info','statement':attack}]
    html=worker_html(pdf.prepare_snapshot(seal(source)))
    assert '<script>' not in html and '<img src="https://evil.invalid/x">' not in html


def test_html_escapes_free_text_and_uses_only_inline_or_fragment_resources(report_case):
    source=context(report_case());attack='<script>"&\'</script><img src="https://evil.invalid/x">'
    source['design_view']['bundle']['project']['name']=attack;source['identity']['name']=attack
    source['method']['limits'][0]['en']=attack
    html=worker_html(pdf.prepare_snapshot(seal(source)));document=Document(html)
    assert attack in ''.join(document.content)
    assert not {'script','iframe','object','embed'}.intersection(document.tags)
    assert not any(name.lower().startswith('on') or name=='srcdoc' for name,_ in document.attrs)
    assert all(value.startswith(('data:','#')) for name,value in document.attrs if name in {'src','href'} and value)
    assert "default-src 'none'" in html and '&lt;script&gt;' in html and '&amp;' in html


def test_verified_snapshot_crosses_worker_without_rendering_opaque_metadata(report_case):
    case=report_case();source=context(case);private='file:///home/private/DO-NOT-PUBLISH'
    source['provenance']['opaque_private_metadata']={'uri':private};seal(source)
    payload=pdf.prepare_snapshot(source)
    assert json.loads(payload['snapshot_json'])['hourly_ac']==source['hourly_ac']
    assert private not in worker_html(payload)
    assert set(payload)=={'snapshot_json','snapshot_sha256','locale','watermark','plan_figure_png'}
    with pytest.raises(TypeError):case.study.native_pdf_document(case.project_id,case.run_id,envelope=source)


@pytest.fixture
def configured_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    for name in ("playwright", "playwright-core"):
        package = root / "node_modules" / name
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"version": "1.64.1", "main": "index.js"}))
    (root / "node_modules/playwright-core/browsers.json").write_text(json.dumps({"browsers": [
        {"name": "chromium", "browserVersion": "synthetic-test-version"}]}))
    # Runtime stub proves fail-closed launch errors without opening a browser.
    (root / "node_modules/playwright/index.js").write_text(
        "module.exports={chromium:{launch:async()=>{throw new Error('private launch log')}}};")
    monkeypatch.setenv("RAWIBUMI_PDF_RUNTIME_ROOT", str(root))
    monkeypatch.setenv("RAWIBUMI_PDF_CHROMIUM_EXECUTABLE", node_binary())
    monkeypatch.setenv("RAWIBUMI_PDF_NODE", node_binary())
    bundle=root/'dist/report-render/report-render.cjs';bundle.parent.mkdir(parents=True)
    bundle.write_text("module.exports={renderReport:()=>\"<!doctype html><html><head><meta http-equiv='Content-Security-Policy' content=\\\"default-src 'none'\\\"></head><body>synthetic</body></html>\"};")
    return root


@pytest.mark.parametrize("mode", ["root_missing", "relative_root", "worker_missing", "module_missing", "launch", "version"])
def test_runtime_failures_are_closed_and_leave_source_untouched(report_case, configured_runtime, monkeypatch, tmp_path, mode):
    case = report_case()
    before = snapshot(case.directory)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(scratch))
    if mode == "root_missing":
        monkeypatch.delenv("RAWIBUMI_PDF_RUNTIME_ROOT")
    elif mode == "relative_root":
        monkeypatch.setenv("RAWIBUMI_PDF_RUNTIME_ROOT", "apps/web")
    elif mode == "worker_missing":
        monkeypatch.setattr(pdf, "WORKER", tmp_path / "absent.cjs")
    elif mode == "module_missing":
        shutil.rmtree(configured_runtime / "node_modules/playwright")
    elif mode == "version":
        (configured_runtime / "node_modules/playwright/package.json").write_text('{"version":"0.0.0"}')
    with pytest.raises(pdf.NativePDFError) as error:
        case.study.native_pdf_document(case.project_id, case.run_id)
    assert "private launch log" not in str(error.value)
    assert str(case.directory) not in str(error.value)
    assert snapshot(case.directory) == before
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("attempt,pages", [("https://evil.invalid/x", 1), ("http://evil.invalid/x", 1),
    ("file:///home/private/secret", 1), ("custom:private", 1), (None, 1), (None, 0), (None, WORKER_PAGE_CAP + 1)])
def test_worker_offline_policy_requests_and_page_limits(report_case, configured_runtime, attempt, pages):
    # A protocol stub inspects options and exercises the route's failure path.
    # These bytes are explicitly synthetic and make no native-PDF validation claim.
    stub = r"""
const assert = require('node:assert/strict');
let handler;
module.exports = {chromium: {launch: async options => {
  assert.equal(options.chromiumSandbox, true);
  assert(!options.args.some(arg => arg.includes('no-sandbox')));
  return {
    version: () => 'synthetic-test-version', close: async () => {},
    newContext: async options => {
      assert.equal(options.javaScriptEnabled, false);
      assert.equal(options.serviceWorkers, 'block');
      assert.equal(options.offline, true);
      assert.equal(options.acceptDownloads, false);
      return {
        route: async (pattern, callback) => { assert.equal(pattern, '**/*'); handler = callback; },
        newPage: async () => ({
          setDefaultTimeout: () => {},
          setContent: async html => {
            assert(html.includes("default-src 'none'"));
            if (ATTEMPT !== null) {
              let aborted = false;
              await handler({request: () => ({url: () => ATTEMPT}),
                abort: async reason => {assert.equal(reason, 'blockedbyclient'); aborted = true;}});
              assert(aborted);
            }
          },
          pdf: async options => {
            assert.equal(options.format, 'A4'); assert.equal(options.printBackground, true);
            assert(!Object.hasOwn(options, 'pageRanges'));
            return (() => {
              const count = PAGE_COUNT;
              const objects = ['<< /Type /Catalog /Pages 2 0 R >>',
                `<< /Type /Pages /Count ${count} /Kids [${Array.from({length: count}, (_, i) => `${i + 3} 0 R`).join(' ')}] >>`,
                ...Array.from({length: count}, () => '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] >>')];
              let raw = '%PDF-1.7\n';
              const offsets = [0];
              objects.forEach((object, i) => { offsets.push(Buffer.byteLength(raw)); raw += `${i + 1} 0 obj\n${object}\nendobj\n`; });
              const xref = Buffer.byteLength(raw);
              raw += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
              raw += offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
              raw += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
              return Buffer.from(raw);
            })();
          }
        })
      };
    }
  };
}}};
""".replace("ATTEMPT", json.dumps(attempt)).replace("PAGE_COUNT", str(pages))
    (configured_runtime / "node_modules/playwright/index.js").write_text(stub)
    case = report_case()
    before = snapshot(case.directory)
    if attempt is None and pages == 1:
        assert case.study.native_pdf_document(case.project_id, case.run_id).startswith(b"%PDF-")
    else:
        diagnostic = "PDF_RESOURCE_REQUEST_BLOCKED" if attempt is not None else "PDF_PAGE_LIMIT"
        with pytest.raises(pdf.NativePDFError, match=diagnostic):
            case.study.native_pdf_document(case.project_id, case.run_id)
    assert snapshot(case.directory) == before


def test_proportional_memory_sampler_reads_current_process():
    known = {}
    rss = pdf._group_rss(os.getpid(), known)
    assert os.getpid() in known
    pss = pdf._group_pss(known)
    assert pss > 0
    assert pss <= rss + 16 * 1024 * 1024


def test_proportional_memory_sampler_rejects_unreadable_live_process(monkeypatch):
    # A live known PID must not silently become a zero-cost process.
    known = {}
    pdf._group_rss(os.getpid(), known)
    real_open = Path.open

    def deny_rollup(path, *args, **kwargs):
        if str(path) == f"/proc/{os.getpid()}/smaps_rollup":
            raise PermissionError("proportional process memory unavailable")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_rollup)
    with pytest.raises(pdf.NativePDFError, match="proportional memory"):
        pdf._group_pss(known)


@pytest.mark.parametrize("mode", ["timeout", "stdout", "stderr", "memory", "bad_pdf"])
def test_worker_process_limits_cleanup_and_no_shell(tmp_path, monkeypatch, mode):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(scratch))
    real_popen = subprocess.Popen
    processes = []
    tracked = {}
    real_rss = pdf._group_rss

    def record_rss(group, known):
        usage = real_rss(group, known)
        tracked.update(known)
        return usage

    monkeypatch.setattr(pdf, "_group_rss", record_rss)
    scripts = {
        "timeout": "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True);time.sleep(30)",
        "stdout": "import sys;sys.stdout.buffer.write(b'x'*2048)",
        "stderr": "import sys;sys.stderr.buffer.write(b'x'*2048)",
        "memory": "import time;time.sleep(30)",
        "bad_pdf": "print('not a PDF')",
    }

    def process_stub(args, **kwargs):
        assert kwargs["shell"] is False and kwargs["start_new_session"] is True
        assert "NODE_OPTIONS" not in kwargs["env"]
        assert Path(kwargs["cwd"]).parent == scratch
        process = real_popen([sys.executable, "-c", scripts[mode]], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(pdf.subprocess, "Popen", process_stub)
    monkeypatch.setattr(pdf, "WORKER_TIMEOUT_SECONDS", 0.5 if mode == "timeout" else 5)
    if mode == "stdout":
        monkeypatch.setattr(pdf, "MAX_PDF_BYTES", 1024)
    if mode == "stderr":
        monkeypatch.setattr(pdf, "MAX_STDERR_BYTES", 1024)
    if mode == "memory":
        monkeypatch.setattr(pdf, "_group_rss", lambda group, known: pdf.MAX_RSS_BYTES + 1)
        monkeypatch.setattr(pdf, "_group_pss", lambda known: pdf.MAX_RSS_BYTES + 1)
    with pytest.raises(pdf.NativePDFError):
        pdf._run_worker(b"{}", tmp_path, Path(sys.executable), Path(sys.executable))
    assert processes and all(p.poll() is not None for p in processes)
    assert list(scratch.iterdir()) == []
    if mode == "timeout":
        assert len(tracked) >= 2, "Detached descendant must be included in resource monitoring"
    # Descendants may briefly remain as zombies until init reaps them, but no
    # process in the killed group may still execute after adapter cleanup.
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
        except FileNotFoundError:
            continue
        if int(fields[2]) == processes[0].pid or int(entry.name) in tracked:
            assert fields[0] == "Z"


def test_native_pdf_integration(report_case, tmp_path):
    from io import BytesIO
    import pikepdf
    for name in ('RAWIBUMI_PDF_RUNTIME_ROOT','RAWIBUMI_PDF_CHROMIUM_EXECUTABLE'):assert os.environ.get(name)
    assert shutil.which('pdfinfo') and shutil.which('pdftotext')
    case=report_case();before=snapshot(case.directory);source=context(case)
    for locale,label in [('en','Reference Production'),('id','Produksi Referensi')]:
        raw=case.study.native_pdf_document(case.project_id,case.run_id,locale=locale)
        assert raw.startswith(b'%PDF-') and len(raw)<=pdf.MAX_PDF_BYTES
        output=tmp_path/f'{locale}.pdf'
        with pikepdf.open(BytesIO(raw)) as document:
            assert document.is_encrypted and document.encryption.R==6 and 1<=len(document.pages)<=8
            for page in document.pages:assert abs(float(page.MediaBox[2])-595.28)<2 and abs(float(page.MediaBox[3])-841.89)<2
            document.save(output,encryption=False)
        extracted=subprocess.check_output(['pdftotext','-layout',str(output),'-'],text=True)
        assert label in extracted and case.project_id in extracted and case.run_id in extracted
        assert source['snapshot_sha256'] in re.sub(r'\s+','',extracted)
        assert ('Plan figure not supplied' if locale=='en' else 'Gambar denah tidak disertakan') in extracted
        assert 'Free /' in extracted and ('simulated period' if locale=='en' else 'periode simulasi') in extracted
    assert snapshot(case.directory)==before
