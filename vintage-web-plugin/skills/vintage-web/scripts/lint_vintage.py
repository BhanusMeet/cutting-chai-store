#!/usr/bin/env python3
"""Lint a file or folder for modern-SaaS patterns banned by the vintage-web skill.

Usage: python lint_vintage.py <path> [--mode web1|editorial|darbar|bombay]
Exit code 0 = clean, 1 = violations found.
"""
import argparse
import re
import sys
from pathlib import Path

EXTS = {".html", ".htm", ".css", ".scss", ".less", ".jsx", ".tsx", ".js", ".ts", ".vue", ".svelte", ".astro"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next"}
BAD_FONTS = ["inter", "roboto", "poppins", "dm sans", "space grotesk", "system-ui", "-apple-system", "sf pro", "segoe ui variable"]
ZERO = re.compile(r"^0+(\.0+)?(px|rem|em|%)?$")
LEN = re.compile(r"^-?\d*\.?\d+(px|rem|em|vw|vh|%)?$")


def blank_comments(text):
    """Remove CSS/HTML/JS block comments but keep line numbering intact."""
    def keep_newlines(m):
        return "\n" * m.group(0).count("\n")
    text = re.sub(r"/\*.*?\*/", keep_newlines, text, flags=re.S)
    text = re.sub(r"<!--.*?-->", keep_newlines, text, flags=re.S)
    return text


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def linked_assets(path, text):
    """Text of local stylesheets/scripts an HTML page links to, so mode essentials
    (palette, fonts, overlays) are judged on the whole page, not just its HTML."""
    out = []
    for m in re.finditer(r"""(?:href|src)\s*=\s*["']([^"':?#]+\.(?:css|js))["']""", text, re.I):
        f = (path.parent / m.group(1)).resolve()
        try:
            out.append(blank_comments(f.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            pass
    return "\n".join(out)


def check(text, mode, extra=""):
    clean = blank_comments(text)
    out = []  # (line, rule, snippet)

    # 1. border-radius anywhere that is not zero
    for m in re.finditer(r"border(?:-[a-z]+)*-radius\s*:\s*([^;}\n]+)", clean, re.I):
        vals = re.sub(r"!important", "", m.group(1), flags=re.I).replace("/", " ").split()
        if not all(ZERO.match(v) or v in ("unset", "initial", "inherit") for v in vals):
            out.append((line_of(clean, m.start()), "rounded corners", m.group(0).strip()))
    for m in re.finditer(r"\brounded(?:-[\w\[\]./%]+)?", clean):
        line = clean.splitlines()[line_of(clean, m.start()) - 1]
        if re.search(r"class(Name)?\s*=|@apply|class:", line) and m.group(0) != "rounded-none":
            out.append((line_of(clean, m.start()), "rounded corners (Tailwind)", m.group(0)))

    # 2. glassmorphism
    for m in re.finditer(r"(?:-webkit-)?backdrop-filter|backdrop-blur", clean, re.I):
        out.append((line_of(clean, m.start()), "glassmorphism (backdrop blur)", m.group(0)))
    for m in re.finditer(r"(?<![\w-])blur\(", clean, re.I):
        out.append((line_of(clean, m.start()), "blur filter", m.group(0)))

    # 3. gradients (hard-stop repeating-linear-gradient allowed for scanlines)
    for m in re.finditer(r"(?<!repeating-)\b(?:linear|radial|conic)-gradient\s*\(", clean, re.I):
        out.append((line_of(clean, m.start()), "gradient", m.group(0)))
    for m in re.finditer(r"repeating-(?:radial|conic)-gradient", clean, re.I):
        out.append((line_of(clean, m.start()), "gradient", m.group(0)))
    for m in re.finditer(r"\bbg-gradient-|\bfrom-\w+-\d+\b.*\bto-\w+-\d+\b", clean):
        out.append((line_of(clean, m.start()), "gradient (Tailwind)", m.group(0)[:40]))

    # 4. blurred / soft shadows
    for m in re.finditer(r"box-shadow\s*:\s*([^;}\n]+)", clean, re.I):
        for layer in re.split(r",(?![^(]*\))", m.group(1)):
            nums = [t for t in re.split(r"\s+", layer.strip()) if LEN.match(t)]
            if len(nums) >= 3 and not ZERO.match(nums[2]):
                out.append((line_of(clean, m.start()), "soft/blurred shadow", m.group(0).strip()))
                break
    for m in re.finditer(r"text-shadow\s*:\s*([^;}\n]+)", clean, re.I):
        nums = [t for t in re.split(r"\s+", m.group(1).strip()) if LEN.match(t)]
        if len(nums) >= 3 and not ZERO.match(nums[2]):
            out.append((line_of(clean, m.start()), "soft/blurred shadow", m.group(0).strip()))
    for m in re.finditer(r"\bshadow-(?:sm|md|lg|xl|2xl)\b", clean):
        out.append((line_of(clean, m.start()), "soft shadow (Tailwind)", m.group(0)))

    # 5. modern default fonts in font-family declarations
    for m in re.finditer(r"font-family\s*:\s*([^;}\n]+)", clean, re.I):
        low = m.group(1).lower()
        for bad in BAD_FONTS:
            if re.search(r"(?<![\w-])" + re.escape(bad) + r"(?![\w-])", low):
                out.append((line_of(clean, m.start()), f"modern font ({bad})", m.group(0).strip()))
                break

    # mode essentials (warnings reported as violations too, they are required)
    low = (clean + "\n" + extra).lower()
    if mode == "web1":
        if ":visited" not in low:
            out.append((1, "missing essential", "define a:visited (classic purple #551A8B)"))
        if "#0000ee" not in low:
            out.append((1, "missing essential", "classic link blue #0000EE not found"))
        if "repeating-linear-gradient" not in low and "scanline" not in low:
            out.append((1, "missing essential", "no CRT scanline overlay found"))
        if not re.search(r"marquee|ticker", low):
            out.append((1, "missing essential", "no marquee/ticker found"))
    if mode == "editorial":
        if "#f4ecd8" not in low:
            out.append((1, "missing essential", "parchment #F4ECD8 not found"))
        if "#2b2520" not in low:
            out.append((1, "missing essential", "aged ink #2B2520 not found"))
        if "feturbulence" not in low:
            out.append((1, "missing essential", "no SVG grain overlay (feTurbulence) found"))
        if "stamp" not in low:
            out.append((1, "missing essential", "no stamp badge found"))
        if "column-count" not in low and "columns:" not in low:
            out.append((1, "missing essential", "no print-column layout found"))
    if mode == "darbar":
        for hexcol, label in [("#d4af37", "antique gold"), ("#6e0d16", "sindoor crimson"), ("#1b365d", "lapis lazuli"),
                              ("#efe3c8", "sandalwood parchment"), ("#1f1916", "kohl ink")]:
            if hexcol not in low:
                out.append((1, "missing essential", f"{label} {hexcol.upper()} not found"))
        for m in re.finditer(r"(?:background(?:-color)?|--[\w-]+)\s*:\s*(?:#fff(?:fff)?|white)\b", clean, re.I):
            out.append((line_of(clean, m.start()), "flat white / modern card ground", m.group(0).strip()))
        if not re.search(r"cinzel|rozha|yatra", low):
            out.append((1, "missing essential", "no Cinzel Decorative / Rozha One / Yatra One display face"))
        if "cormorant" not in low:
            out.append((1, "missing essential", "no Cormorant Garamond body face"))
        if "<svg" not in low or not re.search(r"mehrab|chhatri|arch", low):
            out.append((1, "missing essential", "no inline SVG mehrab/chhatri arch found"))
        if "jali" not in low:
            out.append((1, "missing essential", "no jali lattice divider found"))
        if not re.search(r"rajmudra|seal", low):
            out.append((1, "missing essential", "no Rajmudra seal found"))
        if "feturbulence" not in low:
            out.append((1, "missing essential", "no silk/parchment feTurbulence overlay found"))
        if "prefers-reduced-motion" not in low:
            out.append((1, "missing essential", "no prefers-reduced-motion guard for the farman reveal"))
    if mode == "bombay":
        for hexcol, label in [("#f4c430", "Kaali-Peeli yellow"), ("#141414", "jet black"), ("#e89b54", "sunset sepia")]:
            if hexcol not in low:
                out.append((1, "missing essential", f"{label} {hexcol.upper()} not found"))
        for m in re.finditer(r"#(?:0ff|00ffff|f0f|ff00ff|bf00ff|9d00ff|8a2be2|a020f0|7df9ff|00f0ff)\b", clean, re.I):
            out.append((line_of(clean, m.start()), "neon cyberpunk color", m.group(0)))
        if not re.search(r"bebas|oswald|archivo", low):
            out.append((1, "missing essential", "no Bebas Neue / Oswald / Archivo Black headline face"))
        if not re.search(r"courier prime|ibm plex mono", low):
            out.append((1, "missing essential", "no Courier Prime / IBM Plex Mono typewriter face"))
        if "repeating-linear-gradient" not in low:
            out.append((1, "missing essential", "no VHS/Doordarshan scanline overlay found"))
        if "feturbulence" not in low:
            out.append((1, "missing essential", "no film-grain feTurbulence overlay found"))
        if "halftone" not in low:
            out.append((1, "missing essential", "no halftone dot texture found"))
        if "vhs" not in low:
            out.append((1, "missing essential", "no VHS timestamp badge found"))
        if "column-count" not in low:
            out.append((1, "missing essential", "no newspaper classified columns found"))
        if "prefers-reduced-motion" not in low:
            out.append((1, "missing essential", "no prefers-reduced-motion guard for the REC blink"))
    return out


def iter_files(path):
    p = Path(path)
    if p.is_file():
        yield p
        return
    for f in p.rglob("*"):
        if f.is_file() and f.suffix.lower() in EXTS and not (SKIP_DIRS & set(f.parts)):
            yield f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--mode", choices=["web1", "editorial", "darbar", "bombay"], help="also check mode essentials")
    args = ap.parse_args()

    total = 0
    for f in iter_files(args.path):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"{f}: cannot read ({e})")
            continue
        # essentials only make sense for page-level files, not every stray script
        mode = args.mode if f.suffix.lower() in {".html", ".htm", ".css", ".vue", ".svelte", ".astro", ".jsx", ".tsx"} else None
        extra = linked_assets(f, text) if f.suffix.lower() in {".html", ".htm"} else ""
        for line, rule, snippet in sorted(set(check(text, mode, extra))):
            print(f"{f}:{line}: [{rule}] {snippet}")
            total += 1
    if total:
        print(f"\n{total} violation(s). Fix them and rerun.")
        return 1
    print("vintage-web lint: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
