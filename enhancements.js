/* Small display fixes for VectorNaso's local preview. */
(() => {
  const zoomState = new WeakMap();
  const processed = new WeakSet();
  const replacements = new Set();

  function smoothSvg(svgText) {
    const doc = new DOMParser().parseFromString(svgText, "image/svg+xml");
    if (doc.querySelector("parsererror")) return null;
    for (const shape of doc.querySelectorAll("path, polygon, polyline")) {
      let fill = shape.getAttribute("fill");
      if (!fill || fill === "none") {
        const style = shape.getAttribute("style") || "";
        fill = (style.match(/(?:^|;)\s*fill\s*:\s*([^;]+)/i) || [])[1]?.trim();
      }
      if (!fill || fill === "none" || fill === "currentColor" || fill.startsWith("url(")) continue;
      // Hide hairline seams between neighboring color regions. For near-black
      // ink shapes, retain a slightly stronger dark stroke so linework does
      // not become as faint as the boundaries between shaded regions.
      const hex = fill.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)?.[1];
      let isInk = false;
      if (hex) {
        const full = hex.length === 3 ? [...hex].map(ch => ch + ch).join("") : hex;
        const rgb = [0, 2, 4].map(i => parseInt(full.slice(i, i + 2), 16));
        isInk = Math.max(...rgb) <= 72;
      }
      const dedicatedInk = Boolean(shape.closest("#vectornaso-ink"));
      if (isInk && !dedicatedInk) {
        shape.removeAttribute("stroke");
        shape.removeAttribute("stroke-width");
      } else {
        shape.setAttribute("stroke", dedicatedInk ? "#11100f" : fill);
        shape.setAttribute("stroke-width", dedicatedInk ? "0.45" : "0.65");
      }
      shape.setAttribute("stroke-linejoin", "round");
      shape.setAttribute("stroke-linecap", "round");
      shape.setAttribute("paint-order", "stroke fill");
    }
    return new XMLSerializer().serializeToString(doc.documentElement);
  }

  async function closeSvgGaps(img) {
    if (processed.has(img)) return;
    const src = img.currentSrc || img.src || "";
    if (replacements.has(src)) return;
    if (!src.startsWith("blob:") && !/\.svg(?:$|[?#])|image\/svg\+xml/i.test(src)) return;
    processed.add(img);
    try {
      let svgText;
      if (src.startsWith("data:image/svg+xml")) {
        const payload = src.slice(src.indexOf(",") + 1);
        svgText = /;base64,/i.test(src) ? atob(payload) : decodeURIComponent(payload);
      } else {
        const response = await fetch(src);
        if (!response.ok) return;
        const type = response.headers.get("content-type") || "";
        svgText = await response.text();
        if (!/svg/i.test(type) && !/^\s*(?:<\?xml[^>]*>\s*)?<svg\b/i.test(svgText)) return;
      }
      const fixed = smoothSvg(svgText);
      if (!fixed || !img.isConnected) return;
      const url = URL.createObjectURL(new Blob([fixed], { type: "image/svg+xml" }));
      replacements.add(url);
      img.src = url;
    } catch (_) {
      // Keep the original preview if the browser cannot read its SVG source.
    }
  }

  function enableZoom(img) {
    if (img.dataset.vnZoom === "1") return;
    img.dataset.vnZoom = "1";
    const frame = img.parentElement;
    if (!frame) return;
    frame.title = "Rotellina: zoom · Trascina: sposta · Adatta: ripristina";
    img.classList.add("vn-zoomable");
  }

  function enhance(root = document) {
    for (const img of root.querySelectorAll?.("img") || []) {
      enableZoom(img);
    }
  }

  function start() {
    enhance();
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            if (node.matches?.("img")) {
              enableZoom(node);
            }
            enhance(node);
          }
        }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
  addEventListener("beforeunload", () => replacements.forEach((url) => URL.revokeObjectURL(url)));
})();
