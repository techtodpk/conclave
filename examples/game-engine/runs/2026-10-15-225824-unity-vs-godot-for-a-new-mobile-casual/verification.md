# Claim checks

The checker, `anthropic/claude-opus-5.5`, tested 8 key claims against the pages the members cited. A verdict counts only if the words it quotes are in the page.

Supported: 6. Contradicted: 0. Not found in the sources: 2. Sources could not be read: 0. No source cited: 0.

| # | Claim | Responses | Verdict | Label |
| --- | --- | --- | --- | --- |
| 1 | Unity offers first-party or official integrations with major mobile ad networks, including ad mediation through LevelPlay, while Godot mostly relies on community-maintained plugins. | A, B, C | not found | disputed |
| 2 | Unity canceled its Runtime Fee. | A, B | supported | verified |
| 3 | Under Unity's 2026 pricing, Unity Personal is free up to $200,000 in revenue and funding, and Unity Pro costs $2,310 per seat per year when prepaid. | A, B, C | supported | verified |
| 4 | Godot is MIT-licensed and permits commercial games with no engine royalties or revenue thresholds. | A, B, C | supported | verified |
| 5 | Godot's April 2026 mobile update identifies plugin coverage, performance, testing, and mobile workflows as areas still needing work. | B | supported | verified |
| 6 | Unity's IAP provides a unified purchasing API supporting both the Apple App Store and Google Play. | B | supported | verified |
| 7 | Godot's baseline Android export size is roughly 15–20 MB. | C | not found | disputed |
| 8 | Unity is used by roughly 70% of top mobile games. | A | supported | verified |

## 1. Unity offers first-party or official integrations with major mobile ad networks, including ad mediation through LevelPlay, while Godot mostly relies on community-maintained plugins.

- S1 <https://www.cubix.co/blog/unity-vs-godot-a-game-developers-guide/> (fetched page)
- S2 <https://5stardesigners.com/blog/best-android-game-engine-2026-unity-vs-godot-compared/> (fetched page)
- S5 <https://unity.com/products/levelplay> (not read: beyond the sources checked for one claim)
- S13 <https://aplusgamesstudio.com/blog/unity-vs-godot-mobile-games> (not read: beyond the sources checked for one claim)

S2 says Unity connects directly with AdMob, AppLovin and Unity Ads and that Godot uses community plugins, but no passage mentions LevelPlay mediation.

## 2. Unity canceled its Runtime Fee.

- S3 <https://tech-insider.org/godot-vs-unity-2026/> (fetched page)
- S9 <https://unity.com/blog/terms-update-runtime-fee-cancellation?trk=article-ssr-frontend-pulse_little-text-block> (fetched page)

> We updated the Editor Software Terms to remove language related to the recently canceled Unity Runtime Fee

*Supported by S9.*

## 3. Under Unity's 2026 pricing, Unity Personal is free up to $200,000 in revenue and funding, and Unity Pro costs $2,310 per seat per year when prepaid.

- S3 <https://tech-insider.org/godot-vs-unity-2026/> (fetched page)
- S10 <https://unity.com/products/pricing-updates> (fetched page)
- S12 <https://ziva.sh/blogs/godot-vs-unity> (not read: beyond the sources checked for one claim)

> $2,310/yr per seat, prepaid yearly

*Supported by S10.*

The same page says Personal is available to customers with up to $200,000 in revenue and funding and is free.

## 4. Godot is MIT-licensed and permits commercial games with no engine royalties or revenue thresholds.

- S3 <https://tech-insider.org/godot-vs-unity-2026/> (fetched page)
- S7 <https://github.com/godotengine/godot/blob/master/README.md> (fetched page)
- S11 <https://godotengine.org/license/> (not read: beyond the sources checked for one claim)
- S12 <https://ziva.sh/blogs/godot-vs-unity> (not read: beyond the sources checked for one claim)

> free to use for any purpose, including commercial games, with no revenue thresholds, no royalties, and no subscription fees of any kind.

*Supported by S3.*

## 5. Godot's April 2026 mobile update identifies plugin coverage, performance, testing, and mobile workflows as areas still needing work.

- S8 <https://godotengine.org/article/godot-mobile-update-apr-2026/> (fetched page)

> continued improvements to rendering, performance, testing infrastructure, plugin coverage, and development workflows

*Supported by S8.*

## 6. Unity's IAP provides a unified purchasing API supporting both the Apple App Store and Google Play.

- S6 <https://docs.unity.com/en-us/iap/introduction> (fetched page)

> Unity IAP supports built-in platform stores (Apple App Store and Google Play Store)

*Supported by S6.*

## 7. Godot's baseline Android export size is roughly 15–20 MB.

- S14 <https://www.vectorviral.com/blog-details?slug=unity-vs-godot-mobile-game-startups-2026> (fetched page)

S14 says a minimal Android build 'can be as small as 15-20 MB', which is a lower bound rather than a typical baseline size.

## 8. Unity is used by roughly 70% of top mobile games.

- S4 <https://appradar.com/blog/mobile-game-engines-development-platforms> (fetched page)

> Unity runs about 70% of top mobile games

*Supported by S4.*
