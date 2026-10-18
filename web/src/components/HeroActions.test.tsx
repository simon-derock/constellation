import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HeroActions, mcpUrl } from "./HeroActions";

describe("HeroActions", () => {
  it("offers asking here and connecting over MCP", () => {
    render(<HeroActions />);
    expect(screen.getByRole("link", { name: /Ask the graph/ })).toHaveAttribute("href", "#ask");
    expect(screen.getByRole("button", { name: "Connect over MCP" })).toHaveAttribute("aria-expanded", "false");
  });

  it("shows the MCP address and a client snippet only when asked", async () => {
    render(<HeroActions />);
    expect(screen.queryByRole("region", { name: "Connect over MCP" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Connect over MCP" }));
    expect(screen.getByText(mcpUrl())).toBeInTheDocument();
    expect(screen.getByText(`claude mcp add --transport http constellation ${mcpUrl()}`)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Any client" }));
    expect(screen.getByText(/"mcpServers"/)).toBeInTheDocument();
  });

  it("copies the address to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<HeroActions />);
    await user.click(screen.getByRole("button", { name: "Connect over MCP" }));
    await user.click(screen.getAllByRole("button", { name: "Copy" })[0]!);
    expect(writeText).toHaveBeenCalledWith(mcpUrl());
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("points at the page's own origin when no API address is configured", () => {
    expect(mcpUrl()).toBe(`${window.location.origin}/mcp/`);
  });
});
