# Local Image Sources

All bundled images in `assets/img` come from Kenney free asset packs that were downloaded from the public Kenney website and copied into this demo as a local fallback library.

Primary source packs used in this repository:

- `Background Elements`
  - Source: `https://kenney.nl/assets/background-elements`
  - Files reused for atmospheric background plates such as `villa_exterior.png`, `forest_edge.png`, `mountain_road.png`
- `Top Down Shooter`
  - Source: `https://kenney.nl/assets/top-down-shooter`
  - Files reused for character sprites and prop sprites such as `security_soldier.png`, `tool_bag.png`, `control_console.png`
- `Roguelike RPG Pack`
  - Source: `https://kenney.nl/assets/roguelike-rpg-pack`
  - Files reused for interior and outdoor sample backgrounds such as `mansion_study_room.png`, `estate_garden.png`

Notes:

- These assets are used as a local image library to replace the previous runtime AI image generation path.
- `assets/img/catalog.json` defines the fuzzy-match aliases and tags used by the game when it tries to find the closest local image for a background, NPC, or interactable.
- The raw downloaded archives remain under `.tmp_assets/` for local curation only and are ignored by Git.
