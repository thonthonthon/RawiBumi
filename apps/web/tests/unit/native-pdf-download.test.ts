import { afterEach, describe, expect, it, vi } from "vitest";
import { exportAPI } from "../../src/api";
import { can, setEntitlementSource } from "../../src/platform/entitlements";

const capability = { enabled: false, format: "pdf", text_based: true, locales: ["en", "id"] };
// Binary transport fixture only: deliberately contains bytes that text decoding loses.
const bytes = new Uint8Array([37, 80, 68, 70, 45, 49, 46, 55, 10, 0, 128, 255, 13, 10]);

afterEach(() => {
  vi.unstubAllGlobals();
  setEntitlementSource(null);
});

describe("native PDF HTTP client", () => {
  it.each(["en", "id"] as const)("encodes identifiers, forwards %s and preserves every binary byte", async (locale) => {
    const fetcher = vi.fn().mockResolvedValue(new Response(bytes, {
      headers: { "Content-Type": "Application/PDF; charset=binary", "Content-Disposition": 'attachment; filename="untrusted.pdf"' }
    }));
    vi.stubGlobal("fetch", fetcher);
    const blob = await exportAPI.nativePDF("project /?#é", "run /?#%", locale);
    expect(new Uint8Array(await blob.arrayBuffer())).toEqual(bytes);
    expect(fetcher).toHaveBeenCalledWith(
      `/api/projects/project%20%2F%3F%23%C3%A9/runs/run%20%2F%3F%23%25/exports/native-pdf`,
      { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ locale, plan_figure_png: null }) }
    );
  });

  it.each([true, false])("reads effective server capability enabled=%s without interpreting edition claims", async (enabled) => {
    const value = { ...capability, enabled };
    const fetcher = vi.fn().mockResolvedValue(Response.json(value));
    vi.stubGlobal("fetch", fetcher);
    expect(await exportAPI.nativePDFCapability()).toEqual(value);
    expect(fetcher).toHaveBeenCalledWith("/api/reporting/native-pdf/capability", {
      cache: "no-store", headers: { "Content-Type": "application/json" }
    });
  });

  it.each([null, {}, { ...capability, enabled: "true" }, { ...capability, format: "html" },
    { ...capability, text_based: false }, { ...capability, locales: ["en"] },
    { ...capability, locales: ["en", "id", "fr"] }, { ...capability, locales: "en,id" }
  ])("fails closed on malformed capability %j", async (value) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(value)));
    await expect(exportAPI.nativePDFCapability()).rejects.toThrow("Native PDF capability is unavailable");
  });

  it.each(["text/html", "application/json", "application/octet-stream", "application/pdf-evil", ""])("rejects MIME %s", async (mime) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(bytes, { headers: { "Content-Type": mime } })));
    await expect(exportAPI.nativePDF("p", "r", "en")).rejects.toThrow("application/pdf");
  });

  it.each(["<html>login</html>", '{"detail":"error"}', "x%PDF-1.7", "%pdf-1.7"])("rejects non-PDF bytes despite PDF MIME (%s)", async (body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { headers: { "Content-Type": "application/pdf" } })));
    await expect(exportAPI.nativePDF("p", "r", "en")).rejects.toThrow("not a PDF document");
  });

  it.each([0, 4, 8 * 1024 * 1024 + 1])("rejects invalid byte size %s", async (size) => {
    const body = new Uint8Array(size);
    if (size >= 5) body.set(bytes.slice(0, 5));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { headers: { "Content-Type": "application/pdf" } })));
    await expect(exportAPI.nativePDF("p", "r", "en")).rejects.toThrow("invalid size");
  });

  it.each([404, 422, 500, 503])("preserves sanitized backend JSON errors at status %s", async (status) => {
    const message = status === 503 ? "Native PDF service is unavailable. Please retry later." : "Verified report is unavailable for this project and run.";
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => Response.json({ detail: message }, { status })));
    await expect(exportAPI.nativePDF("p", "r", "en")).rejects.toThrow(message);
    await expect(exportAPI.nativePDFCapability()).rejects.toThrow(message);
  });

  it("keeps a status fallback for non-JSON HTTP errors and propagates connection failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>proxy</html>", { status: 502, statusText: "Bad Gateway" })));
    await expect(exportAPI.nativePDF("p", "r", "en")).rejects.toThrow("Bad Gateway");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));
    await expect(exportAPI.nativePDF("p", "r", "en")).rejects.toThrow("Request failed: 503");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Connection lost")));
    await expect(exportAPI.nativePDFCapability()).rejects.toThrow("Connection lost");
    await expect(exportAPI.nativePDF("p", "r", "id")).rejects.toThrow("Connection lost");
  });

  it("rejects unsupported runtime locales before HTTP", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    await expect(exportAPI.nativePDF("p", "r", "en-US" as "en")).rejects.toThrow("locale must be en or id");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("frontend hints cannot turn disabled server capability into authorization", async () => {
    setEntitlementSource(() => true);
    expect(can("core.export.pdf-native")).toBe(true);
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (path: string) => path.endsWith("/capability")
      ? Response.json(capability)
      : Response.json({ detail: "Native PDF download is unavailable." }, { status: 404 })));
    expect((await exportAPI.nativePDFCapability()).enabled).toBe(false);
    await expect(exportAPI.nativePDF("p", "r", "en")).rejects.toThrow("Native PDF download is unavailable.");
  });
});
