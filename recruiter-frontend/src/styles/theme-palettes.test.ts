import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The failure mode this guards: someone adds a token to one palette, forgets
 * the other, and light mode silently inherits a dark value (or nothing at
 * all) for that one property. Nothing else in the build catches it — the CSS
 * still compiles and every component still renders.
 */
const CSS = readFileSync(join(__dirname, "theme-palettes.css"), "utf8");

function tokensIn(blockPattern: RegExp): string[] {
  const block = CSS.match(blockPattern);
  if (!block) throw new Error(`palette block not found: ${blockPattern}`);
  return [...block[1].matchAll(/^\s*(--[a-z0-9-]+)\s*:/gm)].map((m) => m[1]).sort();
}

describe("theme palettes", () => {
  it("define the same token set in dark and light", () => {
    const dark = tokensIn(/:root,\s*html\.dark\s*\{([\s\S]*?)\n\}/);
    const light = tokensIn(/html\.light\s*\{([\s\S]*?)\n\}/);

    expect(light).toEqual(dark);
  });

  it("keep every colour literal out of the rest of the style layer", () => {
    const geist = readFileSync(join(__dirname, "geist-theme.css"), "utf8");
    // Ignore the grain data-URIs: their feColorMatrix values are filter
    // coefficients, not colours, and they are theme-specific by design.
    const withoutGrain = geist.replace(/url\("data:image\/svg\+xml[^"]*"\)/g, "");

    expect(withoutGrain).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(/);
  });

  it("scrims the modal overlays with a themed token, not flat black", () => {
    // bg-black/80 is right over a near-black ground and wrong over parchment,
    // where it drops a heavy grey sheet over the whole page.
    for (const file of ["dialog.tsx", "sheet.tsx"]) {
      const src = readFileSync(join(__dirname, "..", "components", "ui", file), "utf8");
      expect(src, file).not.toMatch(/bg-black\//);
      expect(src, file).toMatch(/--ed-scrim/);
    }
  });
});
