---
name: vintage-web
description: Build vintage, retro or old-school websites in one of four strictly enforced modes - (1) 90s Web 1.0 (beveled borders, pixel/monospace fonts, marquee tickers, table grids, CRT scanlines, blue/purple visited links), (2) Classic Editorial/Heritage (parchment #F4ECD8, aged ink #2B2520, Playfair/Courier, paper-grain overlay, stamp badges, print columns), (4) Raja-Maharaja Princely Darbar, 1400s-1700s India (illuminated manuscript and miniature-painting frames, antique gold, sindoor crimson, lapis, mehrab/chhatri arches, jali lattice, Rajmudra seals, farman scroll reveals) or (5) 1990s Classic Bombay/Mumbai nostalgia (Kaali-Peeli yellow and black, Marine Drive sunset, VHS/Doordarshan scanlines, BEST bus tickets, Bollywood hoarding posters, cassette covers, classified columns). Use this skill whenever the user asks for a vintage, retro, old-school, nostalgic, throwback, Geocities/Web 1.0, newspaper, heritage, antique, royal Indian, Rajasthani, Mughal, Rajput, maharaja, palace, darbar, miniature painting, Bombay/Mumbai 90s, Bollywood, taxi, VHS or cassette-style website, landing page, portfolio, shop page or UI, even if they never name a mode. It bans modern SaaS gradients, rounded pill buttons and glassmorphism outright.
---

# Vintage Web

Vintage design only reads as authentic when it is *consistent*. A page that mixes a beveled 90s button with a glassy blurred card with a purple-to-blue hero gradient looks like a modern site wearing a costume. This skill exists to stop that: pick one era, commit to its full vocabulary, and keep every modern-SaaS habit out.

Mode 3 is intentionally unassigned (reserved for a future mode); the numbering below matches the names users already use.

## Step 1 - Pick exactly one mode

Choose from the request's cues. Never blend modes; each has its own palette, type and structure.

| Cues in the request | Mode | Reference | Lint `--mode` |
|---|---|---|---|
| 90s, Web 1.0, Geocities, retro computer, pixel, arcade, BBS, CRT, "old internet", hit counter, marquee, early web | **1: 90s Web 1.0** | `references/web1-90s.md` | `web1` |
| editorial, heritage, newspaper, gazette, parchment, antique, letterpress, apothecary, old print, vintage brand/shop, classic, timeless, "old-school" with a refined/premium tone | **2: Classic Editorial/Heritage** | `references/editorial-heritage.md` | `editorial` |
| maharaja, raja, Rajput, Rajasthani, Mughal, darbar, palace, haveli, fort, royal India, miniature painting, illuminated manuscript, pothi, farman, 1400s-1700s, medieval/pre-colonial India | **4: Princely Darbar** | `references/darbar-princely.md` | `darbar` |
| Bombay, Mumbai nostalgia, 90s Mumbai, Kaali-Peeli/taxi, BEST bus, Marine Drive, Bollywood poster, cinema hoarding, VHS, Doordarshan, cassette, Bombay Times/Mid-Day style | **5: 1990s Classic Bombay** | `references/bombay-90s.md` | `bombay` |

If the cues are genuinely ambiguous ("make an old-school site for my bakery"), pick the better fit for the subject (a bakery suits Heritage; a gaming clan suits Web 1.0; a Rajasthani heritage hotel suits Darbar; a Mumbai chai cafe suits Bombay), build it, and say in one line which mode you chose and that the others are available. Do not stop to interview the user about a style you can resolve yourself. An Indian subject does not by itself mean Mode 4 or 5: choose them only for the royal-era or 1990s-Bombay cues above.

## Step 2 - Read the mode's reference, then start from its template

1. Read the matching file in `references/` fully. It holds the palette, type stack, component recipes, bans specific to that mode and a checklist.
2. Copy the matching starter from `assets/` (`web1-template.html`, `editorial-template.html`, `darbar-template.html` or `bombay-template.html`) and adapt it to the user's content. The templates already implement the signature techniques correctly (bevels and scanlines; grain and stamps; SVG arches, jali and seals; checker bands, halftone and tickets), so reuse them rather than re-deriving. Keep output self-contained (inline CSS) unless the project already has a build setup; follow the project's framework if it does, but carry over the same CSS.
3. Write real, period-appropriate copy for the user's subject. Placeholder text kills the illusion. For Modes 4 and 5, keep cultural references accurate and respectful: use real hall, place and route names correctly, never invent Devanagari, Persian or Sanskrit text (use only phrases you are sure of or text the user supplies), and do not use deity imagery or sacred symbols as decoration.

## Step 3 - The ban list (all modes)

These are the visual fingerprints of 2020s SaaS design. They are banned because they instantly date the page to now.

- **Gradients on surfaces, buttons, text or backgrounds** - no `linear-gradient`, `radial-gradient`, `conic-gradient`, no mesh blobs, no purple-to-blue. Metallic gold (Mode 4) and sunsets (Mode 5) are flat fills and hard colour bands, never gradients. Dots, checkers and weaves come from inline SVG `<pattern>`s. *One narrow exception:* a `repeating-linear-gradient` with hard stops is allowed solely to draw CRT/VHS scanlines (Modes 1 and 5), because it renders as lines, not a blend.
- **Rounded or pill buttons, and rounded anything** - `border-radius` is `0` everywhere: buttons, inputs, cards, images, avatars (no circles), badges. No Tailwind `rounded-*` except `rounded-none`. Curved shapes (arches, domes, reels, seals) are allowed only as drawn inline SVG illustration, never as a CSS-rounded UI container; use `clip-path: polygon()` for notched tickets.
- **Glassmorphism** - no `backdrop-filter` / `backdrop-blur`, no frosted translucent panels, no blur glows.
- **Soft shadows** - no blurred `box-shadow`, no floating-card elevation, no hover lift. Depth comes from hard bevels (Mode 1), ruled lines and double borders (Mode 2), zero-blur concentric rings (Mode 4) or hard offset shadows (Mode 5). Zero-blur offset shadows and spread rings are fine.
- **Modern-default type** - no Inter, Roboto, Poppins, DM Sans, Space Grotesk, `system-ui`/`-apple-system` as the face. Use the mode's fonts.
- **SaaS layout tics** - no bento grids, no emoji-in-a-circle feature cards, no "Get started free" hero with two buttons, no generic fade-up or slide-up scroll animations. (Mode 4's farman is a top-to-bottom scroll-unroll wipe, which is allowed because it is a period device, and it must be disabled under `prefers-reduced-motion`.)

Mode-specific extras live in each reference: Mode 4 also bans flat white and white cards; Mode 5 also bans neon purple/cyan and generic minimalist templates.

When a modern pattern is needed functionally, translate it instead of dropping the function:

| Modern pattern | 1: Web 1.0 | 2: Heritage | 4: Darbar | 5: Bombay |
|---|---|---|---|---|
| Pill CTA button | Beveled rectangle, inverts on `:active` | Square, 2px ink border, small caps | Square gold button, crimson border, inset ring | Black button, yellow text, checker-trim border, hard offset shadow |
| Shadowed card | Bordered table cell, `outset`/`inset` | Column block, double rule above | Plaque: ruled gold outline, crimson title bar, diamond finial | Dashed classified ad box, or notched bus/cinema ticket |
| Gradient hero | Flat banner table | Masthead, double rules, stamp | Cusped SVG arch with seal | Hoarding poster: halftone, flat sunset bands, stacked hard-shadow headline |
| Frosted sticky nav | Silver bar of beveled buttons | Solid bar between two rules | Small-caps links between gold rules | Newspaper section strip in Bebas |
| Avatar circle | Square inset photo | Square engraved photo | Square miniature in a multi-border frame | Square halftone photo with caption |
| Toast / modal | Titled dialog box | Boxed notice, double border | Farman scroll | Tear-off ticket or classified box |

## Step 4 - Run the linter before you finish

`scripts/lint_vintage.py` (relative to this skill folder) scans HTML/CSS/JSX/TSX/Vue/Svelte files for every banned pattern above and for missing mode essentials.

```
python scripts/lint_vintage.py <file-or-folder> --mode web1|editorial|darbar|bombay
```

Exit code 1 means a violation; fix it and rerun until clean. A page that passes the linter can still look wrong, so also open it (browser pane or screenshot) and compare it to the reference checklist.

## Craft principles for all modes

- **Authenticity comes from constraint.** Few colors, few fonts, hard edges. If you want a flourish, check whether the era would have had it.
- **Hierarchy through rules, borders and scale** - never through shadow or blur.
- **Subtle texture, readable text.** Scanlines, grain and silk sit at low opacity (about 4-8% for scanlines, 30-45% multiply for grain) with `pointer-events: none` so text stays crisp and clickable.
- **Accessibility survives nostalgia.** Keep body text contrast at 4.5:1 or better (never gold text on parchment), keep visible focus outlines styled in the era's idiom, give images and SVG illustrations `alt` text or `aria-label`, and wrap any motion (marquee, blink, farman reveal) in `@media (prefers-reduced-motion: reduce)` to stop it.
- **Responsive without modernizing.** Collapse tables, grids and columns to a single column on narrow screens; do not introduce rounded mobile drawers or glass bars.
- **Real semantics.** Use real `<table>`, headings, `<nav>`, `<blockquote>`, `<figure>`; the vintage look is a skin, not an excuse for div soup.
