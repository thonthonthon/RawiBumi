import css from "../ui/tokens.css?raw";

const values = new Map(Array.from(css.matchAll(/(--rb-[\w-]+)\s*:\s*([^;{}]+);/g), m => [m[1], m[2].trim()]));
export function reportToken(name: string, ancestors: string[] = []): string {
  const key = `--rb-${name}`;
  if (ancestors.includes(key)) throw new Error(`Cyclic report token: ${key}`);
  const value = values.get(key);
  if (value === undefined) throw new Error(`Missing report token: ${key}`);
  return value.replace(/var\((--rb-[\w-]+)\)/g, (_, alias: string) => reportToken(alias.slice(5), [...ancestors, key]));
}
