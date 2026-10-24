# Supplied UMC design system

Source: user attachment `1-UMC-дизайн-система.zip`, supplied for the UMC developer sprint (2026-10-22). Original archive was safely extracted into `/tmp/umc-design-system-audit`. This directory preserves the supplied CSS, tokens, WOFF2 fonts, brand PNG/SVG assets, component notes and example. No replacement brand assets were generated.

Original ZIP SHA-256: `988715875d60bf678916c7e3a161e539d1cef6fccab9daee53dfb753b6818a6b`.

All 24 supplied files are preserved byte-for-byte; a fresh comparison on 2026-10-24 confirmed their hashes match the ZIP entries. The supplied example already uses the actual flattened `assets/` paths. The original README still mentions obsolete `assets/Logos/` and `assets/Patterns/` paths; production templates use the actual package paths. No correction to the supplied example or assets was needed.

The source declares Oswald and IBM Plex Sans Latin/Cyrillic subsets. Fontconfig inspection confirms these lack the Kazakh pairs Әә (U+04D8/04D9), Ғғ (0492/0493), Ққ (049A/049B), Ңң (04A2/04A3), Өө (04E8/04E9), Һһ (04BA/04BB), and Үү (04AE/04AF). Іі (0406/0456) and Ұұ (04B0/04B1) are present. For coherent Kazakh rendering, the whole `lang=kk` interface uses the system Segoe UI/Arial fallback, with Arial Narrow for headings, rather than mixing missing letters into the branded typeface. Latin and Russian use the supplied local fonts. No remote font request is made.
