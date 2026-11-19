/** UX1 D2 limits, the same as the engine's. */
export const MAX_IMAGE_BYTES = 10 * 1000 * 1000;
export const MAX_IMAGE_SIDE_PX = 8192;

/**
 * MIME and size from a PNG, JPEG or WebP header, without decoding pixels; the engine re-checks the same rules.
 * Returns a reason key instead when the image can't be used.
 */
export function imageHeader(b: Uint8Array): { mime: string; width: number; height: number } | { problem: string } {
  const u32 = (i: number) => ((b[i] << 24) | (b[i + 1] << 16) | (b[i + 2] << 8) | b[i + 3]) >>> 0;
  const u16 = (i: number) => (b[i] << 8) | b[i + 1];
  const le = (i: number, n: number) => { let v = 0; for (let k = n - 1; k >= 0; k--) v = v * 256 + b[i + k]; return v; };
  const ascii = (i: number, n: number) => String.fromCharCode(...b.slice(i, i + n));
  let found: { mime: string; width: number; height: number } | null = null;
  if (b[0] === 0x89 && ascii(1, 3) === "PNG") {
    if (b.length < 24 || ascii(12, 4) !== "IHDR") return { problem: "imagery.badHeader" };
    found = { mime: "image/png", width: u32(16), height: u32(20) };
  } else if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) {
    for (let i = 2; i + 4 <= b.length && !found;) {
      if (b[i] !== 0xff) return { problem: "imagery.badHeader" };
      const m = b[i + 1];
      if (m === 0xd8 || m === 0x01 || (m >= 0xd0 && m <= 0xd7)) { i += 2; continue; }
      if (m >= 0xc0 && m <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(m) && i + 9 <= b.length) found = { mime: "image/jpeg", width: u16(i + 7), height: u16(i + 5) };
      else i += 2 + u16(i + 2);
    }
    if (!found) return { problem: "imagery.badHeader" };
  } else if (ascii(0, 4) === "RIFF" && ascii(8, 4) === "WEBP") {
    const chunk = ascii(12, 4);
    if (chunk === "VP8X" && b.length >= 30) found = { mime: "image/webp", width: 1 + le(24, 3), height: 1 + le(27, 3) };
    else if (chunk === "VP8L" && b.length >= 25 && b[20] === 0x2f) { const bits = le(21, 4); found = { mime: "image/webp", width: (bits & 0x3fff) + 1, height: ((bits >>> 14) & 0x3fff) + 1 }; }
    else if (chunk === "VP8 " && b.length >= 30 && b[23] === 0x9d && b[24] === 0x01 && b[25] === 0x2a) found = { mime: "image/webp", width: le(26, 2) & 0x3fff, height: le(28, 2) & 0x3fff };
    else return { problem: "imagery.badHeader" };
  } else return { problem: "imagery.unsupported" };
  if (b.length > MAX_IMAGE_BYTES) return { problem: "imagery.tooLarge" };
  if (found.width < 1 || found.height < 1 || found.width > MAX_IMAGE_SIDE_PX || found.height > MAX_IMAGE_SIDE_PX) return { problem: "imagery.tooManyPixels" };
  return found;
}
