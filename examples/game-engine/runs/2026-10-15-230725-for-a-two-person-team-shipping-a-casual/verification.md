# Claim checks

The checker, `anthropic/claude-opus-5.5`, tested 8 key claims against the pages the members cited. A verdict counts only if the words it quotes are in the page.

Supported: 5. Contradicted: 0. Not found in the sources: 3. Sources could not be read: 0. No source cited: 0.

| # | Claim | Responses | Verdict | Label |
| --- | --- | --- | --- | --- |
| 1 | Unity Personal is free for companies with under $200,000 in revenue and funding, and Unity Pro costs $2,310 per seat per year when prepaid. | A, B, C | supported | verified |
| 2 | The Godot Foundation is maintaining and improving core Google Play Billing and StoreKit 2 in-app purchase plugins. | B | supported | verified |
| 3 | Godot's April 2026 mobile update identifies mobile plugin coverage, testing and workflow as areas that still need work. | A, B | supported | verified |
| 4 | Unity LevelPlay officially supports mediation integrations with major ad networks including Google AdMob and AppLovin. | B, C | supported | verified |
| 5 | Godot has no official ad mediation support such as LevelPlay and relies on community plugins or custom native bridges. | A, C | not found | disputed |
| 6 | Godot's AdMob support comes from an MIT-licensed community plugin by Poing Studios covering Android and iOS with UMP consent and ATT handling. | A | not found | single model |
| 7 | Poing Studios lists in-app purchase support only as a future plan. | A | not found | single model |
| 8 | Unity canceled the Runtime Fee. | A, B | supported | verified |

## 1. Unity Personal is free for companies with under $200,000 in revenue and funding, and Unity Pro costs $2,310 per seat per year when prepaid.

- S1 <https://unity.com/products/pricing-updates> (fetched page)
- S2 <https://unity.com/en/products/pricing-updates> (fetched page)
- S11 <https://docs.unity3d.com/2023.2/Documentation/Manual/com.unity.services.levelplay.html> (not read: beyond the sources checked for one claim)

> Unity Pro is required if you have over $200,000 in total annual revenue and funding.

*Supported by S1.*

The $2,310/yr prepaid figure is listed as 2026 pricing. Personal being free is implied by the threshold and the 'Free' tier label.

## 2. The Godot Foundation is maintaining and improving core Google Play Billing and StoreKit 2 in-app purchase plugins.

- S8 <https://godotengine.org/article/godot-mobile-update-apr-2026/> (fetched page)

> The Godot Foundation has decided to begin improving and maintaining the core plugins such as Godot Google Play Billing, Godot Google Play Games Services, and Godot StoreKit 2

*Supported by S8.*

## 3. Godot's April 2026 mobile update identifies mobile plugin coverage, testing and workflow as areas that still need work.

- S8 <https://godotengine.org/article/godot-mobile-update-apr-2026/> (fetched page)

> continued improvements to rendering, performance, testing infrastructure, plugin coverage, and development workflows

*Supported by S8.*

## 4. Unity LevelPlay officially supports mediation integrations with major ad networks including Google AdMob and AppLovin.

- S5 <https://docs.unity.com/en-us/grow/levelplay/sdk/unity/mediation-network-guides> (fetched page)
- S10 <https://docs.unity.com/en-us/grow/levelplay/platform/fundamentals/mediated-networks> (fetched page)
- S11 <https://docs.unity3d.com/2023.2/Documentation/Manual/com.unity.services.levelplay.html> (not read: beyond the sources checked for one claim)

> integrating with leading ad networks such as ironSource Ads, Unity Ads, AppLovin, Google AdMob, and Pangle, among others.

*Supported by S10.*

## 5. Godot has no official ad mediation support such as LevelPlay and relies on community plugins or custom native bridges.

- S12 <https://forum.godotengine.org/t/is-there-a-way-to-use-unity-ads-into-godot/95369> (fetched page)
- S3 <https://github.com/poingstudios/godot-admob-ios> (fetched page)

The passages show that community plugins exist. None of them states that Godot lacks official mediation support.

## 6. Godot's AdMob support comes from an MIT-licensed community plugin by Poing Studios covering Android and iOS with UMP consent and ATT handling.

- S3 <https://github.com/poingstudios/godot-admob-ios> (fetched page)

The passages do not mention an MIT license or ATT handling. UMP support appears only in the S5 claim context, not in this excerpt.

## 7. Poing Studios lists in-app purchase support only as a future plan.

- S4 <https://patreon.com/poingstudios> (fetched page)

S4 lists In-App Purchase under 'For future'. The word 'only' is not established by the passage.

## 8. Unity canceled the Runtime Fee.

- S9 <https://unity.com/blog/unity-is-canceling-the-runtime-fee?trk=article-ssr-frontend-pulse_little-text-block> (fetched page)

> we’ve made the decision to cancel the Runtime Fee for our games customers, effective immediately.

*Supported by S9.*

The cancellation applies to games customers only.
