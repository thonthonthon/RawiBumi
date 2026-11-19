import { expect, it } from "vitest";
import config from "../../vite.config";

it("demo never installs an API proxy, even when an API target is configured", () => {
  const previous = process.env.RAWIBUMI_API;
  try {
    for (const target of [undefined, "http://127.0.0.1:41999"]) {
      if (target === undefined) delete process.env.RAWIBUMI_API;
      else process.env.RAWIBUMI_API = target;
      const value = config({ command: "serve", mode: "demo" });
      expect(value.server?.proxy).toBeUndefined();
    }
  } finally {
    if (previous === undefined) delete process.env.RAWIBUMI_API;
    else process.env.RAWIBUMI_API = previous;
  }
});
