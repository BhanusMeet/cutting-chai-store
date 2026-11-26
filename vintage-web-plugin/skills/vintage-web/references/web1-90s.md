# Mode 1 - 90s Web 1.0

Target feel: a hand-coded homepage from 1997-2001. Dense, a little chaotic, proud of itself. Built from tables and borders, not from whitespace and polish.

## Palette (flat, web-safe feel)

| Role | Value |
|---|---|
| Desktop/page background | `#008080` teal, `#000080` navy, or `#C0C0C0` silver (pick one) |
| Panel face | `#C0C0C0` |
| Bevel light / dark / outer | `#FFFFFF` / `#808080` / `#000000` (also `#DFDFDF`, `#404040` for inner edges) |
| Text | `#000000` on silver/white; `#00FF00` or `#FFFF00` on black ticker/terminal panels |
| Link | `#0000EE` |
| Visited link | `#551A8B` |
| Active link | `#FF0000` |
| Accent (use sparingly) | `#FF00FF`, `#FFFF00`, `#00FFFF` for "NEW!" tags and under-construction signs |

Always define `a:link`, `a:visited`, `a:hover`, `a:active` explicitly. The blue/purple visited pair is the strongest single era signal.

## Typography

- Display / headings: `"Press Start 2P"` (Google Fonts), fallback `"Courier New", monospace`. Keep it small (14-22px) because it is wide.
- Terminal / ticker / counters: `"VT323"`, fallback `"Courier New", monospace`, around 20-28px.
- Body: `"Times New Roman", Times, serif` at 16px, or `"Courier New"` for a terminal-leaning site. Plain browser-default serif is authentic.
- Do not use anti-aliased modern sans fonts. Do not use font-weight 300-600 variety; bold or normal only.

## Signature techniques

**Bevel (raised):** `border: 2px solid; border-color: #fff #404040 #404040 #fff; background: #c0c0c0; box-shadow: inset -1px -1px 0 #808080, inset 1px 1px 0 #dfdfdf;`
**Bevel (sunken / inset):** swap the border colors: `#404040 #fff #fff #404040`. Use for text inputs, ticker boxes, counters.
**Button:** raised bevel, `border-radius: 0`, no transition. `:active` flips to sunken and nudges content 1px down/right. Focus: `outline: 1px dotted #000; outline-offset: -4px`.
**Marquee ticker:** a sunken black box with a `VT323` green line scrolling right-to-left using `steps()` for a choppy feel (see template). The legacy `<marquee>` element also works and is on-theme; prefer the CSS version because it can be paused for reduced motion.
**Table grid:** real `<table>` for the page frame (`cellspacing="0" cellpadding="6"`), three columns (nav / content / sidebar) with 2px inset borders between cells. Collapse cells to blocks under ~640px.
**CRT scanlines:** a fixed full-screen `::after` overlay with `repeating-linear-gradient` using hard stops, roughly 4-6% black on 3px rows, `pointer-events: none`. Optionally add a faint vignette using an inset hard-edged `box-shadow: inset 0 0 0 ...` - avoid blurred vignettes. Keep it subtle enough that text remains crisp.
**Horizontal rules:** `<hr>` with `border: 2px inset` or a 4px `ridge`. Never a 1px hairline.

## Period furniture (pick several, do not use all)

Hit counter in a sunken box with zero-padded digits; "Under Construction" sign (a flat yellow box with a thick black border and pixel text; no gradient stripes); "Best viewed in Netscape Navigator at 800x600"; webring links (`<< Prev | Random | Next >>`); guestbook link; "Last updated: <date>"; blinking "NEW!" (steps-based, disabled for reduced motion); tiled background pattern drawn with an inline SVG data URI of pixel dots; 88x31 button-style link badges (square, bevel-framed).

## Copy voice

First person, enthusiastic, slightly over-explained: "Welcome to my corner of the Information Superhighway!" Exclamation marks are fine. Sign off with a webmaster line.

## Checklist before finishing

- [ ] Page frame is a real table or table-like grid with visible bevel/inset borders
- [ ] Pixel or monospace display font loaded, with monospace fallback
- [ ] A marquee/ticker is present and paused under `prefers-reduced-motion`
- [ ] Scanline overlay present, subtle, `pointer-events: none`
- [ ] `a:link #0000EE`, `a:visited #551A8B`, `a:active #FF0000` defined
- [ ] Every `border-radius` is 0; no gradients except scanline hard stops; no blur anywhere
- [ ] Body text contrast 4.5:1+, images have `alt`
- [ ] `python scripts/lint_vintage.py <file> --mode web1` exits 0
