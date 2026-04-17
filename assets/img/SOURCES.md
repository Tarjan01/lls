# Local Image Sources

All bundled images in `assets/img` come from Kenney free asset packs downloaded from the public Kenney website and curated into a local fallback library for this demo.

Current primary packs:

- `Platformer Art Deluxe`
  - Source: `https://kenney.nl/assets/platformer-art-deluxe`
  - Used for doors, windows, clocks, props, and modular room pieces that support the demo's side/front-view presentation.
- `Platformer Characters`
  - Source: `https://kenney.nl/assets/platformer-characters`
  - Used as supporting reference material while curating readable 2.5D-friendly character proportions.
- `Toon Characters`
  - Source: `https://kenney.nl/assets/toon-characters-1`
  - Used for upright NPC sprites such as `detective.png`, `victim.png`, `witness.png`, `security_guard.png`.
- `Background Elements`
  - Source: `https://kenney.nl/assets/background-elements`
  - Used for environmental layers and exterior set dressing such as trees, houses, hills, and atmospheric background plates.

Style note:

- The active demo library now prefers 2.5D, stage-like side/front-view assets instead of top-down sprites.
- `assets/img/catalog.json` is tuned to bias asset resolution toward these side/front-view files when the AI returns approximate names.
- Raw downloaded packs remain under `.tmp_assets/` for local curation only and are not part of the runtime package.
