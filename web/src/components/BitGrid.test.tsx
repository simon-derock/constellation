import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BitGrid, phaseOf } from "./BitGrid";

const HASH = "8" + "0".repeat(62) + "1";
const OTHER = "0".repeat(63) + "3";

describe("BitGrid", () => {
  it("draws one cell per bit and marks the set bits", () => {
    const { container } = render(<BitGrid hash={HASH} label="Proof seal" />);
    const cells = container.querySelectorAll("rect");
    expect(cells).toHaveLength(256);
    expect(container.querySelectorAll('rect[data-on="true"]')).toHaveLength(2);
    expect(container.querySelector("svg")).toHaveAttribute("data-phase", "idle");
  });

  it("is verified when a replay reproduces every bit, and says so to assistive technology", () => {
    const { container, getByRole } = render(<BitGrid hash={HASH} replayed={HASH} label="Proof seal" />);
    expect(container.querySelector("svg")).toHaveAttribute("data-phase", "verified");
    expect(getByRole("img")).toHaveAccessibleName(/identical bits/);
  });

  it("flags exactly the bits that differ", () => {
    const { container, getByRole } = render(<BitGrid hash={HASH} replayed={OTHER} label="Proof seal" />);
    expect(container.querySelector("svg")).toHaveAttribute("data-phase", "mismatch");
    // HASH sets bits 0 and 255, OTHER sets bits 254 and 255: bit 255 agrees, bits 0 and 254 differ
    expect(container.querySelectorAll('rect[data-diff="true"]')).toHaveLength(2);
    expect(getByRole("img")).toHaveAccessibleName(/differs in 2 of 256/);
  });

  it("derives its phase from the two hashes alone", () => {
    expect(phaseOf(HASH)).toBe("idle");
    expect(phaseOf(HASH, HASH)).toBe("verified");
    expect(phaseOf(HASH, OTHER)).toBe("mismatch");
  });
});
