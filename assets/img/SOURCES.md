# Local Image Sources

The checked-in runtime art under `assets/img` is now a curated mix. Backgrounds and detective props have started moving away from the older Kenney placeholders toward a colder noir presentation, while NPC sprites are still mostly temporary stand-ins.

## Raw Package Storage

Keep original downloads and extracted working files under `.tmp_assets/`:

- raw archives: `.tmp_assets/external_sources/`
- extracted curation workspace: `.tmp_assets/external_extract/`

Checked-in runtime files in `assets/img/` should stay filtered, renamed, and cataloged rather than mirroring whole third-party packs.

## Active Runtime Packs

### `CyberNoir - Apartment` by greenly

- Source: `https://greenly.itch.io/cybernoir-apartment`
- Local archive: `.tmp_assets/external_sources/greenly_cybernoir_apartment.zip`
- Local extract root: `.tmp_assets/external_extract/greenly/CyberNoirApartment`
- License note: `CC0`
- Current runtime use:
  - added scene variants: `cybernoir_loft_lounge.png`, `cybernoir_control_desk.png`, `cybernoir_bunk_corridor.png`

### `Free Visual Novel Backgrounds (Mansion Pack)` by Potat0Master

- Source: `https://potat0master.itch.io/free-visual-novel-backgrounds-mansion-pack`
- Local archive: `.tmp_assets/external_sources/potat0master_mansion_pack.zip`
- Local extract root: `.tmp_assets/external_extract/potato/MansionUpdated_1080p_WEBP`
- License note from source page: royalty-free for personal and commercial use, but do not redistribute the original downloaded pack
- Current runtime use:
  - `mansion_foyer_night.webp`
  - `mansion_velvet_hallway.webp`
  - `mansion_basement_chamber.webp`
  - `mansion_courtyard_gate.webp`

### `Free Pixel Art 32x32 - Detective Mystery Pack` by Kabukidanshi

- Source: `https://kabukidanshi.itch.io/pixel-art-32x32-detective-mystery-pack`
- Local archive: `.tmp_assets/external_sources/kabukidanshi_detective_mystery_pack.rar`
- Local extract root: `.tmp_assets/external_extract/kabuki`
- License note from source page: free for personal and commercial use with attribution; do not redistribute or resell the original pack
- Current runtime use:
  - previously curated exact copies: `case_file.png`, `guest_register.png`, `handgun_tool.png`, `knife_tool.png`, `locked_door.png`, `open_door.png`, `tool_case.png`, `window.png`
  - added clue props: `brass_key.png`, `padlock.png`, `sealed_letter.png`, `opened_letter.png`, `flashlight_on.png`, `magnifying_glass.png`, `safe_box_closed.png`, `safe_box_opened.png`, `wallet_closed.png`, `burner_phone.png`

## Still Temporary

- `assets/img/npcs` remains mostly placeholder silhouette work and should be replaced later with a less cartoon character set.
- Some older runtime backgrounds are still legacy exports or placeholder selections and can be phased out case by case.

## Pending Paid Pack

- `Pixel Art Detective Icon & Character Asset Pack` by howdy riceball
  - Source: `https://howdyriceball.itch.io/pixel-art-detective-icon-asset-pack`
  - Status: not checked in; purchase/download required before runtime integration
- `Detective Hand Drawn Icons Asset Pack` by howdy riceball
  - Source: `https://howdyriceball.itch.io/detective-hand-drawn-icons-asset-pack`
  - Status: only a local preview/demo image is currently present as `assets/img/ui/detective_handdrawn_demo.png`
