from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import base64
from io import BytesIO
import json
import re
import sys
import threading
import time
import webbrowser

import vtracer

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
HOST = "127.0.0.1"
PORT = 8766
MAX_BODY = 50 * 1024 * 1024


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print("VectorNaso:", fmt % args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()
        if self.path in (
            "/assets/branding/VectorNaso.ico",
            "/assets/branding/VectorNaso_Icona.png",
            "/assets/branding/VectorNaso-Splash.jpeg",
            "/editor.js",
            "/enhancements.js",
        ):
            return super().do_GET()
        if self.path == "/health":
            body = json.dumps({
                "ok": True,
                "engine": "VTracer",
                "build": "2026-10-20-vector-exports-v4",
                "root": str(ROOT),
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        if self.path not in ("/trace", "/export"):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                self._json(413, {"error": "Immagine troppo grande (limite 50 MB)."})
                return
            payload = json.loads(self.rfile.read(length))
            if self.path == "/export":
                self._export(payload)
                return
            image = base64.b64decode(payload["image"], validate=True)
            profile = payload.get("profile", "art")
            detail = max(1, min(5, int(payload.get("detail", 4))))
            colors = payload.get("colors", "auto")
            line_art = payload.get("lineArt") is True

            requested_colors = (
                2 if line_art
                else 12 if colors == "auto" and profile != "photo"
                else None if colors == "auto"
                else max(2, min(64, int(colors)))
            )
            monochrome = payload.get("monochrome") is True
            if monochrome or line_art:
                # A color trace contains separate paths for white interior
                # regions. Recoloring every one of them black fills enclosed
                # spaces (for example the inside of a badge) into a blob.
                # BW mode traces the dark artwork independently of palette
                # quantization, preventing white regions turning gray.
                cfg = vtracer.Config.bw()
            else:
                cfg = vtracer.Config.photo() if profile == "photo" else vtracer.Config()
            cfg.mode = "spline"
            # Keep coordinates precise to a tenth of a trace pixel while
            # reducing SVG text size. Level 2 optimizes path commands; palette
            # selection and the independently traced contour layer stay intact.
            cfg.path_precision = 1
            cfg.optimize = 2
            # Stacked keeps broad color regions underneath their refinements.
            # This avoids the tiled/mosaic look of cutout and better preserves
            # the layered shading seen in illustrated artwork.
            cfg.hierarchical = "stacked"
            cfg.filter_speckle = [18, 12, 8, 6, 4][detail - 1]
            cfg.simplify = [2.5, 2.0, 1.6, 1.3, 1.1][detail - 1]
            # Balance color merging with faithful local hues. The contour mask
            # is traced independently, while the fill trace keeps enough
            # precision to retain small colored details and original tones.
            cfg.color_precision = [5, 5, 5, 6, 6][detail - 1]
            cfg.layer_difference = [46, 44, 42, 40, 38][detail - 1]
            protected_palette = None
            if not monochrome and not line_art and profile != "photo" and payload.get("inkImage"):
                ink_bytes = base64.b64decode(payload["inkImage"], validate=True)
                protected_palette = self._protected_palette(image, ink_bytes, requested_colors)
            if protected_palette:
                # Reserve the outline and white explicitly in the user's color
                # budget. Palette sampling ignores the separately traced ink
                # mask and near-white areas, so dark contour pixels cannot
                # pull the illustrated fills toward muddy colors.
                cfg.palette = protected_palette
                cfg.max_colors = None
            else:
                cfg.max_colors = requested_colors
            if monochrome or line_art:
                # Keep tiny lettering, but fit smoother splines over the
                # supersampled binary edge instead of following pixel steps.
                cfg.filter_speckle = 1
                cfg.corner_threshold = 120
                cfg.simplify = [2.5, 2.3, 2.1, 1.9, 1.7][detail - 1]
            elif profile != "photo":
                # Color illustrations are traced at 2x resolution. Scale the
                # area filter accordingly, discard tiny tonal islands, and fit
                # broader splines to reduce stair-stepping in color boundaries.
                # Preserve small highlights and facial details in flat-color
                # illustrations; the previous stronger area filter erased
                # small but meaningful regions such as eye glints and badges.
                cfg.filter_speckle = [36, 28, 20, 18, 14][detail - 1]
                cfg.corner_threshold = 112
                cfg.simplify = [3.8, 3.4, 3.0, 2.8, 2.6][detail - 1]

            if (monochrome or line_art) and payload.get("inkImage"):
                # The prepared tracing mask is fully opaque (white canvas,
                # black artwork). Feeding the transparent color-prepared PNG
                # to BW mode makes VTracer treat transparent pixels as black,
                # creating a solid rectangular backdrop around the drawing.
                trace_image = base64.b64decode(payload["inkImage"], validate=True)
            else:
                trace_image = image
            svg = cfg.convert_bytes(trace_image)
            if monochrome or line_art:
                mono_color = payload.get("monoColor", "#000000")
                # BW output can contain a white region for the mask's canvas.
                # Drop that region before recoloring, otherwise it becomes a
                # solid foreground rectangle in the exported monochrome SVG.
                svg = self._drop_white_paths(svg)
                if monochrome:
                    if not isinstance(mono_color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", mono_color):
                        mono_color = "#000000"
                    # Recolor each remaining traced region uniformly while preserving geometry.
                    svg = re.sub(
                        r'''(?i)(\bfill\s*=\s*)(["'])(.*?)\2''',
                        lambda match: match.group(0)
                        if match.group(3).strip().lower() == "none"
                        or match.group(3).strip().lower().startswith("url(")
                        else match.group(1) + match.group(2) + mono_color + match.group(2),
                        svg,
                    )
                    svg = re.sub(
                        r'''(?i)(\bfill\s*:\s*)#[0-9a-f]{3,8}\b''',
                        lambda match: match.group(1) + mono_color,
                        svg,
                    )
            elif profile != "photo" and payload.get("inkImage"):
                # Vector tracing can merge near-white fills with adjacent
                # grays. Trace bright neutral regions separately and place
                # them over the palette result, below the dark ink overlay.
                if payload.get("whiteImage"):
                    white_bytes = base64.b64decode(payload["whiteImage"], validate=True)
                    white_cfg = vtracer.Config.bw()
                    white_cfg.mode = "spline"
                    white_cfg.path_precision = 1
                    white_cfg.optimize = 2
                    white_cfg.hierarchical = "stacked"
                    white_cfg.filter_speckle = 2
                    white_cfg.corner_threshold = 120
                    white_cfg.simplify = [2.5, 2.3, 2.1, 1.9, 1.7][detail - 1]
                    white_svg = self._drop_white_paths(white_cfg.convert_bytes(white_bytes))
                    svg = self._overlay_color(svg, white_svg, "#ffffff", "vectornaso-white")

                # Restore only crisp dark linework over the color regions.
                # The frontend mask includes dark antialias blends so colored
                # fringes are restored as black along the original contours.
                ink_bytes = base64.b64decode(payload["inkImage"], validate=True)
                ink_cfg = vtracer.Config.bw()
                ink_cfg.mode = "spline"
                ink_cfg.path_precision = 1
                ink_cfg.optimize = 2
                ink_cfg.hierarchical = "stacked"
                ink_cfg.filter_speckle = [4, 3, 2, 2, 1][detail - 1]
                ink_cfg.corner_threshold = 112
                # Keep the mask close to the source contour. A looser fit
                # makes the black overlay overshoot colored regions.
                ink_cfg.simplify = [1.8, 1.6, 1.4, 1.2, 1.0][detail - 1]
                ink_svg = ink_cfg.convert_bytes(ink_bytes)
                svg = self._overlay_ink(svg, ink_svg)
            if profile != "photo":
                # Trace coordinates are doubled for antialias-aware fitting.
                # Explicitly bind the viewport to those coordinates before
                # restoring the original physical SVG dimensions. VTracer's
                # viewBox may be absent or stale after SVG postprocessing;
                # halving width/height alone can then crop the right/bottom.
                width, height = self._svg_size(svg)
                try:
                    svg = re.sub(
                        r"<svg\b([^>]*)>",
                        lambda match: "<svg" + re.sub(
                            r'''\sviewBox\s*=\s*(["']).*?\1''',
                            "",
                            match.group(1),
                            flags=re.IGNORECASE,
                        ) + f' viewBox="0 0 {width} {height}">',
                        svg,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                    physical_width, physical_height = str(float(width) / 2), str(float(height) / 2)
                    svg = re.sub(r'\bwidth="[0-9.]+', f'width="{physical_width}', svg, count=1)
                    svg = re.sub(r'\bheight="[0-9.]+', f'height="{physical_height}', svg, count=1)
                except (TypeError, ValueError):
                    pass
            paths = svg.count("<path")
            width, height = self._svg_size(svg)
            self._json(200, {"svg": svg, "paths": paths, "width": width, "height": height})
        except Exception as exc:
            self._json(500, {"error": f"Conversione fallita: {exc}"})

    def _export(self, payload):
        """Convert the traced SVG to vector PDF, EPS, or DXF and return bytes."""
        from urllib.parse import quote

        fmt = str(payload.get("format", "")).lower()
        svg = payload.get("svg", "")
        if fmt not in {"pdf", "eps", "dxf"}:
            self._json(400, {"error": "Formato di esportazione non supportato."})
            return
        if not isinstance(svg, str) or "<svg" not in svg[:1000].lower():
            self._json(400, {"error": "Il contenuto SVG non è valido."})
            return

        if fmt == "pdf":
            from svglib.svglib import svg2rlg
            from reportlab.graphics import renderPDF

            drawing = svg2rlg(BytesIO(svg.encode("utf-8")))
            if drawing is None:
                raise ValueError("Impossibile leggere il disegno SVG.")
            data = renderPDF.drawToString(drawing)
            if isinstance(data, str):
                data = data.encode("latin-1", errors="replace")
            content_type = "application/pdf"
        elif fmt == "eps":
            data = self._svg_to_eps(svg)
            content_type = "application/postscript"
        else:
            data = self._svg_to_dxf(svg)
            content_type = "application/dxf"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote('vectornaso.' + fmt)}")
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _svg_to_eps(svg):
        """Write filled SVG paths as portable, vector-only EPS/PostScript."""
        from svgpathtools import parse_path, CubicBezier, QuadraticBezier, Line
        from xml.etree import ElementTree as ET
        import math

        root = ET.fromstring(svg)
        parents = {child: parent for parent in root.iter() for child in parent}
        view_box = root.attrib.get("viewBox", "0 0 512 512").replace(",", " ").split()
        if len(view_box) == 4:
            min_x, min_y, width, height = map(float, view_box)
        else:
            min_x = min_y = 0.0
            width = float(re.search(r'width="([0-9.]+)', svg).group(1))
            height = float(re.search(r'height="([0-9.]+)', svg).group(1))

        def inherited_fill(element):
            node = element
            while node is not None:
                fill = node.attrib.get("fill")
                style = node.attrib.get("style", "")
                style_fill = re.search(r"(?:^|;)\s*fill\s*:\s*([^;]+)", style)
                if style_fill:
                    fill = style_fill.group(1).strip()
                if fill:
                    return fill
                node = parents.get(node)
            return "#000000"

        def postscript_path(d):
            commands = []
            path = parse_path(d)
            previous = None
            for segment in path:
                if previous is None or abs(segment.start - previous) > 1e-7:
                    commands.append(f"{segment.start.real:.4f} {segment.start.imag:.4f} moveto")
                if isinstance(segment, CubicBezier):
                    commands.append(
                        f"{segment.control1.real:.4f} {segment.control1.imag:.4f} "
                        f"{segment.control2.real:.4f} {segment.control2.imag:.4f} "
                        f"{segment.end.real:.4f} {segment.end.imag:.4f} curveto"
                    )
                elif isinstance(segment, QuadraticBezier):
                    p0, q, p2 = segment.start, segment.control, segment.end
                    c1 = p0 + (q - p0) * (2 / 3)
                    c2 = p2 + (q - p2) * (2 / 3)
                    commands.append(
                        f"{c1.real:.4f} {c1.imag:.4f} {c2.real:.4f} {c2.imag:.4f} "
                        f"{p2.real:.4f} {p2.imag:.4f} curveto"
                    )
                elif isinstance(segment, Line):
                    commands.append(f"{segment.end.real:.4f} {segment.end.imag:.4f} lineto")
                else:
                    count = max(3, min(48, int(segment.length(error=0.2) / 2) + 1))
                    commands.extend(
                        f"{segment.point(i / count).real:.4f} {segment.point(i / count).imag:.4f} lineto"
                        for i in range(1, count + 1)
                    )
                previous = segment.end
                if abs(segment.end - segment.start) < 1e-7:
                    commands.append("closepath")
            return "\n".join(commands)

        box_w = max(1, math.ceil(width * 0.75))
        box_h = max(1, math.ceil(height * 0.75))
        output = [
            "%!PS-Adobe-3.0 EPSF-3.0",
            "%%Creator: VectorNaso",
            f"%%BoundingBox: 0 0 {box_w} {box_h}",
            f"%%HiResBoundingBox: 0 0 {width * 0.75:.3f} {height * 0.75:.3f}",
            "%%LanguageLevel: 2",
            "%%Pages: 1",
            "%%EndComments",
            "gsave",
            "0.75 0.75 scale",
            f"-{min_x:.4f} -{min_y:.4f} translate",
            f"0 {height:.4f} translate",
            "1 -1 scale",
        ]
        count = 0
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "path" or not element.attrib.get("d"):
                continue
            fill = inherited_fill(element).strip()
            color = re.fullmatch(r"#([0-9a-fA-F]{6})", fill)
            if fill.lower() == "none" or not color:
                continue
            rgb = color.group(1)
            red, green, blue = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
            output.extend((
                "gsave",
                f"{red:.5f} {green:.5f} {blue:.5f} setrgbcolor",
                "newpath",
                postscript_path(element.attrib["d"]),
                "eofill",
                "grestore",
            ))
            count += 1
        if not count:
            raise ValueError("Nessun tracciato colorato da esportare in EPS.")
        output.extend(("grestore", "%%EOF", ""))
        return "\n".join(output).encode("ascii")

    @staticmethod
    def _svg_to_dxf(svg):
        """Flatten SVG Bezier paths into colored DXF polylines and solid hatches."""
        import ezdxf
        from ezdxf.colors import DXF_DEFAULT_COLORS
        from svgpathtools import parse_path
        from xml.etree import ElementTree as ET

        root = ET.fromstring(svg)
        parents = {child: parent for parent in root.iter() for child in parent}
        view_box = root.attrib.get("viewBox", "0 0 512 512").replace(",", " ").split()
        if len(view_box) == 4:
            min_x, min_y, width, height = map(float, view_box)
        else:
            min_x = min_y = 0.0
            width = float(re.search(r'width="([0-9.]+)', svg).group(1))
            height = float(re.search(r'height="([0-9.]+)', svg).group(1))
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 0  # SVG pixel-like user units, no implicit unit conversion.
        msp = doc.modelspace()
        added = 0

        def dxf_color(rgb):
            """Return an ACI fallback and retain the exact RGB true color."""
            channels = ((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255)
            # White vector regions are the page/background in the source art;
            # leaving them unfilled also avoids CAD viewers' ACI-7 ambiguity.
            if min(channels) >= 248 and max(channels) - min(channels) <= 5:
                return None, rgb
            # ACI 7 is rendered black on a light page and white on a dark one.
            # Keep near-black shapes legible on the white Illustrator artboard.
            if max(channels) <= 30:
                return 7, rgb
            best_index = min(
                range(1, min(256, len(DXF_DEFAULT_COLORS))),
                key=lambda index: sum(
                    (channels[axis] - ((DXF_DEFAULT_COLORS[index] >> shift) & 255)) ** 2
                    for axis, shift in enumerate((16, 8, 0))
                ),
            )
            return best_index, rgb

        def signed_area(points):
            return sum(
                points[index][0] * points[(index + 1) % len(points)][1]
                - points[(index + 1) % len(points)][0] * points[index][1]
                for index in range(len(points))
            ) / 2

        def contains_point(polygon, point):
            x, y = point
            inside = False
            previous = polygon[-1]
            for current in polygon:
                x1, y1 = previous
                x2, y2 = current
                if (y1 > y) != (y2 > y):
                    crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
                    if x < crossing_x:
                        inside = not inside
                previous = current
            return inside

        def flatten(d):
            path = parse_path(d)
            segments = []
            points = []
            previous = None
            for segment in path:
                if previous is None or abs(segment.start - previous) > 1e-7:
                    if points:
                        segments.append(points)
                    points = [(segment.start.real, segment.start.imag)]
                count = max(2, min(32, int(segment.length(error=0.2) / 3) + 1))
                points.extend((segment.point(i / count).real, segment.point(i / count).imag)
                              for i in range(1, count + 1))
                previous = segment.end
            if points:
                segments.append(points)
            return segments

        def inherited_fill(element):
            node = element
            while node is not None:
                fill = node.attrib.get("fill")
                style_fill = re.search(r"(?:^|;)\s*fill\s*:\s*([^;]+)", node.attrib.get("style", ""))
                if style_fill:
                    fill = style_fill.group(1).strip()
                if fill:
                    return fill
                node = parents.get(node)
            return "#000000"

        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "path" or not element.attrib.get("d"):
                continue
            fill = inherited_fill(element)
            match = re.fullmatch(r"#([0-9a-fA-F]{6})", fill.strip())
            color = int(match.group(1), 16) if match else 0x000000
            aci, true_color = dxf_color(color)
            if aci is None:
                continue
            # Keep all geometry on layer 0 so Illustrator preserves the SVG
            # painter's order. Per-color layers can reorder overlapping fills.
            contours = []
            for points in flatten(element.attrib["d"]):
                if len(points) < 2:
                    continue
                coords = [(x - min_x, height - (y - min_y)) for x, y in points]
                closed = len(coords) > 2 and abs(coords[0][0] - coords[-1][0]) < 0.05 and abs(coords[0][1] - coords[-1][1]) < 0.05
                if closed:
                    coords[-1] = coords[0]
                    contours.append(coords[:-1])
                else:
                    msp.add_lwpolyline(coords, dxfattribs={"color": aci, "true_color": true_color})
                    added += 1
            if contours:
                hatch = msp.add_hatch(color=aci, dxfattribs={"true_color": true_color})
                for index, contour in enumerate(contours):
                    # DXF hatches need all loops from one compound SVG path in
                    # the same entity; mark nested loops as holes or islands.
                    sample = contour[0]
                    depth = sum(
                        1 for other_index, other in enumerate(contours)
                        if other_index != index and abs(signed_area(other)) > abs(signed_area(contour))
                        and contains_point(other, sample)
                    )
                    flags = 1 if depth % 2 == 0 else 0
                    hatch.paths.add_polyline_path(contour, is_closed=True, flags=flags)
                added += 1
        if not added:
            raise ValueError("Nessun tracciato esportabile nel documento SVG.")
        from io import StringIO
        stream = StringIO()
        doc.write(stream)
        return stream.getvalue().encode("utf-8")

    @staticmethod
    def _svg_size(svg):
        import re
        width = re.search(r'\bwidth="([0-9.]+)', svg)
        height = re.search(r'\bheight="([0-9.]+)', svg)
        return (width.group(1) if width else "—", height.group(1) if height else "—")

    @staticmethod
    def _protected_palette(image_bytes, ink_bytes, requested_colors):
        """Build a compact fill palette without letting linework set its colors."""
        from PIL import Image

        if not requested_colors:
            return None
        fill_slots = max(0, requested_colors - 2)
        palette = ["#11100f", "#ffffff"]
        if fill_slots == 0:
            return palette

        with Image.open(BytesIO(image_bytes)) as source_file:
            source = source_file.convert("RGBA")
        with Image.open(BytesIO(ink_bytes)) as mask_file:
            mask = mask_file.convert("L")
        if mask.size != source.size:
            mask = mask.resize(source.size, Image.Resampling.NEAREST)

        # A bounded sample keeps palette generation responsive on large scans.
        source.thumbnail((640, 640), Image.Resampling.BOX)
        mask = mask.resize(source.size, Image.Resampling.NEAREST)
        pixels = source.load()
        mask_pixels = mask.load()
        samples = bytearray()
        for y in range(source.height):
            for x in range(source.width):
                r, g, b, alpha = pixels[x, y]
                if alpha < 24 or mask_pixels[x, y] < 128:
                    continue
                high, low = max(r, g, b), min(r, g, b)
                luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
                # Keep near-white fills in the dedicated white layer. This
                # avoids spending a palette slot on antialiasing noise.
                if luminance >= 235 and high - low <= 30:
                    continue
                samples.extend((r, g, b))

        if not samples:
            return palette
        sample_count = len(samples) // 3
        if fill_slots == 1:
            sums = [0, 0, 0]
            for offset in range(0, len(samples), 3):
                sums[0] += samples[offset]
                sums[1] += samples[offset + 1]
                sums[2] += samples[offset + 2]
            colors = [tuple(round(total / sample_count) for total in sums)]
        else:
            sample_image = Image.frombytes("RGB", (sample_count, 1), bytes(samples))
            quantized = sample_image.quantize(
                colors=fill_slots,
                method=Image.Quantize.MEDIANCUT,
                dither=Image.Dither.NONE,
            )
            color_indices = sorted({index for _, index in quantized.getcolors(sample_count)})
            color_table = quantized.getpalette()
            colors = [tuple(color_table[index * 3:index * 3 + 3]) for index in color_indices]

        for r, g, b in colors:
            color = f"#{r:02x}{g:02x}{b:02x}"
            if color.lower() not in {entry.lower() for entry in palette}:
                palette.append(color)
        return palette[:requested_colors]

    @staticmethod
    def _drop_white_paths(svg):
        def keep_path(match):
            tag = match.group(0)
            fill = re.search(r'''\bfill\s*=\s*(["'])(.*?)\1''', tag, re.IGNORECASE)
            if not fill:
                return tag
            color = fill.group(2).strip().lower()
            if color in {"white", "#fff", "#ffffff", "#fffffff", "#ffffffff"}:
                return ""
            return tag

        return re.sub(r"<path\b[^>]*(?:/>|>)", keep_path, svg, flags=re.IGNORECASE)

    @staticmethod
    def _emphasize_ink(svg):
        def emphasize(match):
            tag = match.group(0)
            fill = re.search(r'''\bfill\s*=\s*(["'])(#[0-9a-fA-F]{3,8})\1''', tag)
            if not fill:
                return tag
            color = fill.group(2)[1:]
            if len(color) == 3:
                color = ''.join(ch * 2 for ch in color)
            if len(color) != 6:
                return tag
            red, green, blue = (int(color[i:i + 2], 16) for i in (0, 2, 4))
            # Target ink and near-black details only; leave dark colors such
            # as Mario's brown hair and blue shadows untouched.
            if max(red, green, blue) <= 72:
                # The independent BW ink pass handles these shapes; avoid a
                # second dark outline that would make the line too heavy.
                return tag
            attrs = f' stroke="{fill.group(2)}" stroke-width="0.65" stroke-linejoin="round" stroke-linecap="round" paint-order="stroke fill"'
            # Keep the slash at the very end for SVG self-closing elements.
            if tag.endswith("/>"):
                return tag[:-2] + attrs + "/>"
            return tag[:-1] + attrs + ">"

        return re.sub(r"<path\b[^>]*>", emphasize, svg)

    @staticmethod
    def _overlay_ink(color_svg, ink_svg):
        paths = re.findall(r"<path\b[^>]*>", ink_svg)
        if not paths:
            return color_svg

        ink_paths = []
        for tag in paths:
            # BW tracing uses black foreground; normalize it while keeping
            # the original traced contour width.
            tag = re.sub(r'''\bfill\s*=\s*(["'])[^"']*\1''', 'fill="#11100f"', tag)
            ink_paths.append(tag)

        overlay = '<g id="vectornaso-ink" fill="#11100f">' + "".join(ink_paths) + "</g>"
        return re.sub(r"</svg\s*>", lambda match: overlay + match.group(0), color_svg, count=1)

    @staticmethod
    def _overlay_color(color_svg, mask_svg, color, group_id):
        paths = re.findall(r"<path\b[^>]*>", mask_svg)
        if not paths:
            return color_svg
        color_paths = [
            re.sub(r'''\bfill\s*=\s*(["'])[^"']*\1''', f'fill="{color}"', tag)
            for tag in paths
        ]
        overlay = f'<g id="{group_id}" fill="{color}">' + "".join(color_paths) + "</g>"
        return re.sub(r"</svg\s*>", lambda match: overlay + match.group(0), color_svg, count=1)

    def _json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"VectorNaso pronto: {url}")
    print("Elaborazione locale. Chiudi questa finestra per terminare.")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
