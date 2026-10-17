import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { webcrypto } from "node:crypto";
import { afterEach } from "vitest";

// without Vitest globals, Testing Library does not unmount between tests, and one test's DOM leaks into the next
afterEach(cleanup);

// jsdom has no SubtleCrypto; the seal hash needs it, so tests borrow Node's
if (!globalThis.crypto?.subtle) Object.defineProperty(globalThis, "crypto", { value: webcrypto });
