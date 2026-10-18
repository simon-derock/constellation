// publishes the scroll offset as --y on the root; the stylesheet decides how far each layer travels, so the
// effect costs one passive listener and one write per frame
export function startParallax(): () => void {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return () => {};
  let frame = 0;
  const write = () => {
    frame = 0;
    document.documentElement.style.setProperty("--y", String(Math.round(window.scrollY)));
  };
  const onScroll = () => {
    if (!frame) frame = requestAnimationFrame(write);
  };
  write();
  window.addEventListener("scroll", onScroll, { passive: true });
  return () => {
    window.removeEventListener("scroll", onScroll);
    if (frame) cancelAnimationFrame(frame);
  };
}
