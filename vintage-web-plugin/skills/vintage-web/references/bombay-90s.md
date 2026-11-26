# Mode 5 - 1990s Classic Bombay / Retro Mumbai Nostalgia

Target feel: a 1994 Bombay afternoon - Kaali-Peeli taxis, a BEST bus ticket crumpled in a pocket, a hand-painted film hoarding, Doordarshan on a CRT, a Bombay Times classifieds page, a cassette with a handwritten J-card, sunset at Marine Drive. Warm, loud, slightly worn, full of local texture.

## Palette (flat ink on newsprint)

| Role | Value |
|---|---|
| Kaali-Peeli taxi yellow | `#F4C430` |
| Jet black | `#141414` |
| Marine Drive sunset sepia-orange | `#E89B54` |
| Newsprint (page ground; supporting color) | `#EFE6D2` |
| Hoarding poster red (sparing accent; supporting color) | `#C1272D` |

Banned palette: neon purple, neon cyan, magenta glow, any "cyberpunk" tones. Sunset is flat orange bands, never a gradient. Text pairs: black on yellow, black on newsprint, yellow on black, black on sunset.

## Typography

- Headlines: `"Bebas Neue"` or `"Oswald"` (condensed, tall, uppercase) and `"Archivo Black"` for poster-weight slogans. Fallback `Impact, "Arial Narrow", sans-serif`.
- Editorial body: `"Lora"` for articles and `"Courier Prime"` or `"IBM Plex Mono"` for classified text, tickets, VHS on-screen text and prices.
- Poster headline effect: stacked hard text-shadows in black and red (`4px 4px 0 #141414`), zero blur. Optional outlined text with `-webkit-text-stroke`.
- Real, local copy: place names (Colaba, Dadar, Marine Drive, Churchgate), bus route numbers, fares in rupees. Never fake-Hindi; if Devanagari or Hinglish is used it must be correct or user-supplied.

## Signature techniques

**Kaali-Peeli band:** a checkered black-and-yellow strip as an inline SVG `<pattern>` (data URI background), 12-16px squares, used as page header/footer trim and on buttons' borders.
**VHS / Doordarshan layer:** fixed scanline overlay with `repeating-linear-gradient` and hard stops (about 5-8% black, 3px rows; this is the one allowed gradient). Add a VHS on-screen badge: `REC` + a blinking square dot (steps animation) and a monospace timestamp like `SP  04:17 PM  12 NOV 1994` in yellow on black.
**Warm film grain:** a fixed SVG `feTurbulence` overlay tinted warm brown, `mix-blend-mode: multiply`, opacity about 0.3, `pointer-events: none`.
**Halftone:** dots from an inline SVG `<pattern>` as the background of headline blocks and the poster, in sunset or black at 15-25% opacity. Never radial-gradient dots.
**BEST bus ticket card:** a narrow, tall slip: Courier/IBM Plex Mono text, dashed tear lines, stage numbers, fare row, serial number, and notched edges made with `clip-path: polygon(...)` (zigzag or square notches). No rounded corners.
**Cinema ticket card:** wide stub with a perforation line (`border-left: 3px dashed`), "ADMIT ONE", hall, show time, seat, price; notches via `clip-path`.
**Cassette card:** an inline SVG illustration (reels as SVG circles are fine; illustration only, never UI containers) with a handwritten-label area holding the text.
**Newspaper classified columns:** `column-count: 3`, `column-rule: 1px solid #141414`, tiny uppercase run-in heads (`WANTED`, `TO-LET`, `MATRIMONIAL`-style structure without actual personal data), boxed ads with `2px dashed` borders, and a thick rule masthead; mixes yellow-highlighted ads on newsprint.
**Hand-painted poster hero:** big stacked headline in Bebas/Archivo with hard offset shadows, slightly rotated blocks (-2 to 3 degrees), halftone fill, a flat sunset-band skyline SVG (sun, stripes, Queen's Necklace dot arc), and a "NOW SHOWING" tag.
**Buttons:** rectangular, black ground with yellow text and a 3px yellow-and-black checker-trim border; hover inverts; hard 3px offset shadow with zero blur is allowed.

## Layout patterns

Masthead (newspaper title, dateline, "Rs. 3.00") -> checker band -> poster hero -> three-column classifieds / editorial with ticket cards inline -> cassette "playlist" section -> footer with a BEST-route style strip. Dense and slightly cluttered, like newsprint; leave less whitespace than modern sites.

## Copy voice

Warm, local, a little cheeky: "Dadar se Dadar tak, sab milega." Newspaper-headline brevity. Avoid startup language.

## Strict bans (in addition to the global ban list)

No glassmorphism, no neon cyberpunk purple/cyan, no generic minimalist templates (large empty white space, thin sans, rounded cards), no smooth sunset gradients, no rounded UI.

## Checklist before finishing

- [ ] `#F4C430`, `#141414` and `#E89B54` all present
- [ ] Bebas/Oswald/Archivo headlines with Courier Prime / IBM Plex Mono / Lora text
- [ ] Scanline overlay (hard-stop gradient) plus warm grain overlay
- [ ] Halftone via SVG pattern; checker band via SVG pattern
- [ ] A VHS timestamp badge; a ticket or cassette card; multi-column classifieds
- [ ] Blink/animation disabled under `prefers-reduced-motion`
- [ ] No neon purple/cyan; every `border-radius` is 0
- [ ] `python scripts/lint_vintage.py <file> --mode bombay` exits 0
