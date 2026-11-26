# Mode 2 - Classic Editorial / Heritage

Target feel: a well-kept broadsheet, a letterpress catalogue, an apothecary label. Warm, ruled, confident, a little worn. Authority comes from typography and structure, not decoration.

## Palette

| Role | Value |
|---|---|
| Parchment (page background) | `#F4ECD8` |
| Aged ink (all text, rules, borders) | `#2B2520` |
| Slightly darker paper (panels, table stripes) | `#EADFC4` |
| Faded ink (secondary text, captions) | `#5A4E42` |
| Stamp red / oxblood | `#9B2C20` |
| Optional second stamp ink (navy) | `#2F4A5C` |
| Optional gilt accent (rules, ornaments only, not text) | `#A8863B` |

Use at most the ink + one stamp color per page. Everything is flat; there are no tints beyond these.

## Typography

- Display / masthead / headlines: `"Playfair Display", "Didot", Georgia, serif`, weights 700-900, tight leading (1.05-1.15), often uppercase for the masthead.
- Body: `"Libre Baskerville", "Baskerville", Georgia, serif`, 17-18px, line-height 1.6-1.7.
- Typewriter details (datelines, captions, stamps, prices, labels): `"Courier Prime", "Courier New", monospace`, uppercase, letter-spacing 0.12-0.2em, small size.
- Use small caps (`font-variant: small-caps`) for navigation and section labels, and a drop cap on the lead paragraph.
- Use real typographic punctuation: curly quotes, em dashes, section signs, fleurons.

## Signature techniques

**Paper grain overlay:** a fixed full-screen pseudo-element whose background is an SVG `feTurbulence` noise (data URI, see template and `assets/paper-grain.svg`), `mix-blend-mode: multiply`, opacity about 0.35-0.5, `pointer-events: none`. It should be felt, not seen. Optionally add a second very faint blotch layer by tiling a larger-scale turbulence at lower opacity.
**Ruled structure:** the masthead sits between a thick top rule and a `3px double` bottom rule; sections are separated by `1px solid` ink rules; the footer repeats the double rule. Rules do the job shadows would do in a modern UI.
**Print columns:** body copy in `column-count: 3` with `column-gap: 2rem` and `column-rule: 1px solid #2B2520`, dropping to 2 then 1 column responsively. Use `text-align: justify` with `hyphens: auto` for the column text. Headlines and figures use `column-span: all`.
**Stamp badges:** square-cornered, `3px double` border in stamp red, Courier uppercase text, rotated -4 to -8 degrees, `mix-blend-mode: multiply`, and distressed with an inline SVG `feTurbulence` + `feDisplacementMap` filter (`filter: url(#rough)`) so the edges look inked unevenly. Typical texts: "EST. 1924", "SATISFACTION GUARANTEED", "No. 1 of 500", "APPROVED".
**Photos:** `filter: sepia(.5) contrast(1.05)` plus a 1px ink border with 6px parchment mat (`outline` or `padding` + background), always square-cornered, with a Courier caption below.
**Buttons:** rectangular, `2px solid #2B2520`, transparent background, Courier or small-caps label, `border-radius: 0`; hover/focus inverts to ink background with parchment text. Focus keeps a visible `outline: 2px solid #9B2C20; outline-offset: 3px`.
**Ornaments:** use typographic ornaments (`* * *`, `&#10086;`, `&sect;`) as dividers instead of icons.

## Layout patterns

- Masthead: dateline row (Vol., date, price/edition) in Courier -> giant Playfair title -> double rule -> small-caps nav.
- Lead story: large headline spanning columns, deck (italic subhead), byline in Courier, then columns of text with a drop cap.
- Sidebars as ruled boxes ("Notices", "Weather", "Classifieds") with a heading in small caps.
- Product/shop pages: catalogue entries with numbered plates, Courier prices, a stamp for status ("IN STOCK", "LIMITED").
- Footer: colophon with printer's marks ("Set in Playfair & Baskerville"), double rule above.

## Copy voice

Measured, formal, a touch ceremonial: "Purveyors of Fine Goods Since 1924." Headlines are declarative; mastheads read like proper nouns. Avoid exclamation marks and startup vocabulary ("seamless", "supercharge").

## Checklist before finishing

- [ ] Background `#F4ECD8` and text `#2B2520` used as the base pair
- [ ] Playfair (or Didot/Georgia fallback) display + Courier detail type loaded
- [ ] Paper-grain SVG overlay present, subtle, `pointer-events: none`
- [ ] At least one distressed stamp badge
- [ ] Multi-column print layout with column rules and a drop cap
- [ ] Double rules in masthead/footer; no shadows, no gradients, no blur, every `border-radius` 0
- [ ] Body contrast 4.5:1+, images have `alt`, visible focus styles
- [ ] `python scripts/lint_vintage.py <file> --mode editorial` exits 0
