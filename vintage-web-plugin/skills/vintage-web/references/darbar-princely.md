# Mode 4 - Raja-Maharaja & Princely Darbar (1400s-1700s)

Target feel: an illuminated royal manuscript or a Rajput/Mughal-era miniature painting, set inside a palace. Every container is an engraved plaque, an unrolled farman (royal decree) or a palace archway. Nothing looks like a modern UI card.

## Palette (flat pigment, like mineral paint on parchment)

| Role | Value |
|---|---|
| Page ground: sandalwood parchment | `#EFE3C8` |
| Ink and rods: charcoal kohl | `#1F1916` |
| Antique gold (rules, fills, seals; never body text on parchment) | `#D4AF37` |
| Sindoor crimson (borders, banners, wax) | `#6E0D16` |
| Lapis lazuli (panels, plaque fields, jali ground) | `#1B365D` |
| Optional darker parchment for inset areas | `#E3D3AE` |

Text pairs that pass 4.5:1: kohl on sandalwood, sandalwood on crimson, sandalwood or gold on lapis. Gold on parchment fails; use it only for lines and ornaments there. Never use pure white; the lightest tone is sandalwood.

## Typography

- Display / titles: `"Cinzel Decorative"` for carved-stone titles; `"Rozha One"` or `"Yatra One"` for bolder heads and anything in Devanagari. Always give serif fallbacks (`Georgia, serif`).
- Body: `"Cormorant Garamond"`, 20-22px, line-height 1.55, weight 500 for legibility (its light weights are too thin on parchment).
- Use small caps and wide tracking for labels. Use real Devanagari only for phrases you are certain of (for example `॥ श्री ॥`) or text the user supplies; never invent Devanagari, Persian or Sanskrit text, and avoid deity imagery or sacred symbols as decoration.

## Signature techniques

**Miniature-painting frame (multi-border):** nest borders with hard, zero-blur rings, for example on the page frame: `border: 6px solid #6E0D16; outline: 2px solid #D4AF37; outline-offset: -12px;` plus `box-shadow: 0 0 0 3px #D4AF37, 0 0 0 11px #1B365D, 0 0 0 13px #D4AF37;`. Zero-blur spread rings are allowed; any blur is banned.
**Scalloped mehrab / chhatri arches:** draw them as inline SVG paths, never with `border-radius`. The template has a cusped (pointed, multifoil) arch and a `<symbol id="chhatri">` domed pavilion that repeats in a row as a skyline. A pearl-fringe along an arch edge is a dashed round-cap stroke.
**Jali latticework:** an SVG `<pattern>` of interlocking diamonds and dots in gold on lapis, used as a divider strip (28-40px tall) between sections.
**Rajmudra seal:** circular SVG: two concentric rings, text along a circle with `<textPath>`, a central sun or lotus motif, filled in brass gold with kohl linework. Use it once or twice (header, footer, beside a signature).
**Silk and parchment texture:** a fixed overlay of SVG `feTurbulence`; use an anisotropic `baseFrequency` like `0.02 0.9` for horizontal silk-thread streaks and a finer isotropic layer for paper grain, `mix-blend-mode: multiply`, opacity 0.35-0.5, `pointer-events: none`.
**Plaque:** the only container type. Parchment or lapis ground, an inner `outline` ruled in gold, corner ornaments drawn as small SVG or CSS squares, and a title bar in crimson. Square corners always.
**Farman reveal:** each content section unrolls like a scroll when it enters the viewport: a `clip-path: inset(0 0 100% 0)` to `inset(0)` wipe over about 1.4s with an ease-out curve, bracketed by kohl rods with gold end-caps. It must be a wipe that reveals content top to bottom, not a fade-up or slide-up. Add the hidden initial state only when JavaScript is running (`.js .farman`), and show everything immediately under `prefers-reduced-motion: reduce`.
**Buttons:** square, kohl text on gold with a crimson 3px border and an inset gold ring; hover swaps to crimson ground with sandalwood text; focus uses a 3px lapis outline with offset.

## Layout patterns

Hero is a tall arch (SVG) holding the title and a seal; below it a jali strip; then plaques in a 2-column or 4-up grid on lapis; a farman scroll for the main announcement or story; a chhatri skyline row above the footer; footer with a seal and a colophon in small caps. Use symmetric, centred composition: palace architecture is symmetrical.

## Copy voice

Formal, ceremonial, third person: "By the grace of the House, the Darbar is open to guests." Use titles (Maharaja, Rajkumari, Diwan) and hall names (Diwan-i-Aam, Sheesh Mahal, Toshakhana) correctly and with respect. No startup vocabulary.

## Strict bans (in addition to the global ban list)

No flat white cards, no pure white anywhere, no drop-shadow boxes, no pill or rounded anything, no modern icon sets, no sans-serif UI chrome, no stock neon or tech blues. Metallic gold is a flat `#D4AF37` fill; it is never a gradient.

## Checklist before finishing

- [ ] All five palette colors present; no `#fff`/`white`
- [ ] Cinzel Decorative or Rozha/Yatra for display, Cormorant Garamond for body
- [ ] Inline SVG arch, a chhatri row, a jali strip and a Rajmudra seal
- [ ] Multi-border miniature frame made from zero-blur rings
- [ ] Silk/parchment `feTurbulence` overlay, subtle, `pointer-events: none`
- [ ] Farman unroll reveal that is disabled under `prefers-reduced-motion`
- [ ] Every container reads as plaque, scroll or arch; zero `border-radius`
- [ ] `python scripts/lint_vintage.py <file> --mode darbar` exits 0
