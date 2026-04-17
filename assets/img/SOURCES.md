# Local Image Sources

The checked-in runtime art under `assets/img` is still a temporary fallback library. It was assembled quickly from Kenney packs so the demo could stay playable while AI scene generation, caching, and UI iteration were still in flux.

Temporary fallback packs currently in use:

- `Platformer Art Deluxe`
  - Source: `https://kenney.nl/assets/platformer-art-deluxe`
  - Current role: placeholder doors, windows, clocks, props, and modular room pieces.
- `Platformer Characters`
  - Source: `https://kenney.nl/assets/platformer-characters`
  - Current role: placeholder upright character silhouettes and support references.
- `Toon Characters`
  - Source: `https://kenney.nl/assets/toon-characters-1`
  - Current role: placeholder NPC sprites such as `detective.png`, `victim.png`, `witness.png`, `security_guard.png`.
- `Background Elements`
  - Source: `https://kenney.nl/assets/background-elements`
  - Current role: placeholder environmental layers and exterior set dressing.

## Preferred Art Direction

The next curation pass should stop leaning on bright cartoon packs and move toward a cooler, noir-leaning 2.5D presentation:

- muted palette, high contrast, cleaner silhouettes
- side/front-view or VN-style staged composition
- crime, investigation, gallery, manor, security-room, basement, and urban-night moods
- avoid chibi proportions and overtly toy-like props

## Recommended Replacement Libraries

These were selected as the best fit for the current detective/crime demo pipeline on 2026-04-17.

### 1. Background library for manor / gallery / indoor mystery scenes

- `Free Visual Novel Backgrounds (Mansion Pack)` by Potat0Master
  - Source: `https://potat0master.itch.io/free-visual-novel-backgrounds-mansion-pack`
  - Why it fits: strong hall, foyer, basement, mansion exterior, and interior coverage; darker lighting variants; much closer to a crime-scene/VN backdrop than the current Kenney placeholders.
  - Licensing notes from source page: royalty-free for personal and commercial projects; editing allowed; redistribution of the downloaded files is not allowed.

### 2. Background library for colder urban / surveillance / cyber-noir scenes

- `CyberNoir - Apartment` by greenly
  - Source: `https://greenly.itch.io/cybernoir-apartment`
  - Why it fits: moody noir atmosphere, sharper visual-novel framing, and strong support for control-room, clinic, apartment, and dystopian investigation scenes.
  - Licensing notes from source page: `CC0`.

### 3. Interactable prop library for clues / locks / crime-scene items

- `Free Pixel Art 32x32 - Detective Mystery Pack` by Kabukidanshi
  - Source: `https://kabukidanshi.itch.io/pixel-art-32x32-detective-mystery-pack`
  - Why it fits: includes clue-friendly detective props such as keys, flashlights, padlocks, files, letters, doors, knives, and blood-stain variants that map cleanly onto the current interactable schema.
  - Licensing notes from source page: free for personal and commercial use with attribution; redistribution/resale not allowed.

### 4. UI accent / portrait / icon library for a less cartoon detective tone

- `Pixel Art Detective Icon & Character Asset Pack` by howdy riceball
  - Source: `https://howdyriceball.itch.io/pixel-art-detective-icon-asset-pack`
  - Why it fits: compact noir/detective-oriented icons plus character material suitable for menu overlays, dossier panels, and side portraits.
  - Licensing notes from source page: `CC BY 4.0`, paid pack.
- `Detective Hand Drawn Icons Asset Pack` by howdy riceball
  - Source: `https://howdyriceball.itch.io/detective-hand-drawn-icons-asset-pack`
  - Why it fits: useful for case-board UI, notebook tabs, evidence panels, and menu accents when the pixel set feels too game-jam-like.
  - Licensing notes from source page: `CC BY-SA 4.0`, paid pack.

## Planned Runtime Mapping

When the placeholder art is replaced, the local asset resolver should be curated along these lines:

- `assets/img/backgrounds`: primarily Potat0Master mansion scenes, with greenly noir scenes for more modern or urban cases.
- `assets/img/interactables`: primarily Kabukidanshi detective props.
- `assets/img/npcs`: curated portrait/silhouette exports from the chosen VN-style or noir character packs.
- menu/backdrop overlays: a dimmed protagonist portrait plus noir icon accents, rather than bright cartoon character cutouts.

## Runtime Notes

- `assets/img/catalog.json` is already structured so the art swap can stay data-driven once replacement files are curated locally.
- Raw downloaded packs should stay under `.tmp_assets/` for curation only and should not be used directly at runtime without filtering, renaming, and catalog tagging.
