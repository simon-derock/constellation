import { describe, expect, it } from "vitest";
import { ownerAt, type Interval } from "./ownership";

const titan: Interval[] = [
  { owner: "Bill", from: -1000, to: -579, origin: "former_owner", start_known: false, evidence: "EVT-a" },
  { owner: "Sharon", from: -579, to: -306, origin: "former_owner", start_known: false, evidence: "EVT-b" },
  { owner: "Sam", from: 2, to: null, origin: "claim", start_known: true, evidence: "EVT-c" },
];

describe("ownerAt", () => {
  it("gives a handover day to the new holder (half-open intervals)", () => {
    expect(ownerAt(titan, -580)?.owner).toBe("Bill");
    expect(ownerAt(titan, -579)?.owner).toBe("Sharon");
    expect(ownerAt(titan, 2)?.owner).toBe("Sam");
  });

  it("reports an orphaned gap as nobody, not as the previous owner", () => {
    expect(ownerAt(titan, -306)).toBeUndefined();
    expect(ownerAt(titan, 1)).toBeUndefined();
  });

  it("treats a missing end as still open", () => {
    expect(ownerAt(titan, 10_000)?.owner).toBe("Sam");
  });
});
