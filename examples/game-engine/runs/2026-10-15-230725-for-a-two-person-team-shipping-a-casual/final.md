# For a two-person team shipping a casual game on Android and iOS with ads and in-app purchases, which engine has the lower total cost and risk over three years?

*Conclave full run, 2026-10-15 23:07, profile 'plan'. Members searched the web and cited 12 pages. 8 key claims were checked against them: 5 verified, 0 contradicted, 3 not confirmed.*

## Answer

For a typical two-person team with comparable experience in both engines, Unity is the better default for lower risk over three years. Godot always has the lower licence cost and no licence-terms risk. Unity's lower total cost is likely but not proven. It is a judgment about integration labour, not a measured result.

**Licence cost.** Unity Personal is free while the company's total annual revenue plus funding stays under $200,000. Above that, Pro costs $2,310 per seat per year when prepaid. For two seats over three full years at today's prices, that is about $13,860. Godot is MIT-licensed and costs nothing at any revenue level. This confirms C2 and C3.

**Integration risk.** This is what decides the question, because ads and purchases are your revenue.
- Unity has an official cross-store IAP API (confirming C4).
- Unity's LevelPlay officially mediates major ad networks such as AdMob and AppLovin. This resolves the Unity side of the earlier dispute D1.
- Godot is weaker on mobile, but less weak than some answers claimed. The Godot Foundation now maintains the Google Play Billing and StoreKit 2 purchase plugins. Godot's own April 2026 update still lists plugin coverage, testing and workflows as unfinished (confirming C5).
- No member confirmed any official Godot ad-mediation support.

**Break-even.** If Unity Pro is needed for all three years, Unity must save more than about $13,860 in labour and delays to come out ahead. At $50 per hour, that is roughly 277 developer-hours. Below the $200K threshold, Unity has no fee to recover.

**When to pick Godot instead.** Choose Godot if your team already knows it well and can show rewarded ads and purchase flows working on real Android and iOS devices. That includes restoring purchases and handling interrupted ones.

## Key claims

1. Unity Personal is free under $200,000 in combined revenue and funding, and Unity Pro costs $2,310 per seat per year when prepaid. [verified]
2. Two Pro seats for three years at unchanged prices cost about $13,860. [agreed but unchecked]
3. Unity canceled the Runtime Fee, so it does not belong in the cost model. [verified]
4. Godot's MIT licence allows commercial games with no royalties or revenue thresholds. [verified]
5. Unity LevelPlay officially supports mediation with major networks, including AdMob and AppLovin. [verified]
6. Unity IAP provides one purchasing API covering both the App Store and Google Play. [agreed but unchecked]
7. The Godot Foundation is maintaining and improving the core Google Play Billing and StoreKit 2 plugins. [verified]
8. Godot's April 2026 update lists mobile plugin coverage, testing and workflows as areas that still need work. [verified]
9. Godot has no official ad mediation and relies on community plugins or custom native bridges. [disputed]
10. Godot's AdMob support comes from Poing Studios' community plugin. [single model]
11. Unity has the lower risk-adjusted total cost for an equally experienced team. This is an engineering judgment. [agreed but unchecked]

## Disagreements

- **How strong Unity's advantage is.** Response C calls it "significantly lower" risk and says Godot's maintenance cost exceeds $13,860. Responses A and B hedge. The review by B's author and the review by A's author both found C's figures unsupported. The hedged view is the better-supported one.
- **Whether Godot IAP depends on volunteers.** Response A found no maintained IAP plugin, and Response C implied Godot relies on community wrappers or custom bridges. Response B pointed to the Foundation-maintained billing plugins, and the checker verified this. B is correct.
- **Whether the fee threshold is per game.** Response C says Pro applies only if "the game" exceeds $200K. The reviews by A's and B's authors note that the threshold counts total company revenue plus funding. The checked Unity page supports the reviewers.
- **Whether the team will stay under the threshold.** Response A says a small team is "likely" to stay under $200K. The review by B's author called this an unsupported prediction. It remains an assumption.

## Open questions

- How large is the real integration and maintenance labour gap between the two engines? No evidence quantifies it.
- How healthy are Godot's ad plugins and its newer billing plugins today? Test the specific ad networks you plan to use, on real devices.
- What are your team's skills, and what revenue and funding do you expect? Either could reverse the recommendation.
- Will Unity change its pricing or terms within the three years?
- The earlier figures C6 (Unity's market share), C7 (which engine suits which kind of 3D) and D2 (Godot's Android export size) were not rechecked in this run.

## Sources

- S1: [Unity pricing updates](https://unity.com/products/pricing-updates), cited by A, B
- S2: [Unity pricing updates](https://unity.com/en/products/pricing-updates), cited by A
- S3: [Godot AdMob plugin](https://github.com/poingstudios/godot-admob-ios), cited by A
- S4: [Poing Studios](https://patreon.com/poingstudios), cited by A
- S5: [LevelPlay integration](https://docs.unity.com/en-us/grow/levelplay/sdk/unity/mediation-network-guides), cited by B
- S6: [Unity IAP](https://docs.unity.com/en-us/iap/introduction), cited by B
- S7: [Godot license](https://godotengine.org/license/), cited by B
- S8: [Godot mobile update](https://godotengine.org/article/godot-mobile-update-apr-2026/), cited by B
- S9: [Unity cancellation announcement](https://unity.com/blog/unity-is-canceling-the-runtime-fee?trk=article-ssr-frontend-pulse_little-text-block), cited by B
- S10: [Mediated networks](https://docs.unity.com/en-us/grow/levelplay/platform/fundamentals/mediated-networks), cited by B
- S11: [Unity Pricing](https://docs.unity3d.com/2023.2/Documentation/Manual/com.unity.services.levelplay.html), cited by C
- S12: [Godot Engine ironSource discussion](https://forum.godotengine.org/t/is-there-a-way-to-use-unity-ads-into-godot/95369), cited by C

## How this answer was made

Each member answered alone, then reviewed the others' answers with the authors hidden behind letters. The chairman, `anthropic/claude-opus-5.5`, wrote this page from the answers and reviews, and from the claim checks in verification.md.

| Response | Model | Peer ranking (average position, lower is better) |
| --- | --- | --- |
| B | `openai/gpt-6.1-sol` | 1.0 (2 reviews) |
| A | `anthropic/claude-sonnet-5.5` | 1.5 (2 reviews) |
| C | `google/gemini-3.8-flash` | 2.0 (2 reviews) |

Readable rankings: 3 of 3.

## What changed in memory

- Added C8: Two Unity Pro seats for three years at unchanged prepaid prices of $2,310 per seat per year cost about $13,860. [agreed but unchecked] (may repeat C2)
- Added C9: Unity LevelPlay officially supports ad mediation with major networks, including AdMob and AppLovin. [verified]
- Added C10: The Godot Foundation maintains and is improving the core Google Play Billing and StoreKit 2 in-app purchase plugins for Godot. [verified]
- Added C11: For a two-person mobile team with equal experience in Unity and Godot, Unity likely has the lower risk-adjusted three-year total cost, but this is an engineering judgment about integration labour rather than a measured result. [agreed but unchecked]
- Changed C2: Under Unity's 2026 pricing, Unity Personal is free while the company's total annual revenue plus funding stays under $200,000, which is not a per-game threshold, and Unity Pro costs $2,310 per seat per year when prepaid. [agreed but unchecked] (was: Under Unity's 2026 pricing, Unity Personal is free up to $200,000 in revenue and funding, and Unity Pro costs $2,310 per seat per year when prepaid.)
- Opened dispute D3: Whether Godot has no official ad mediation and relies only on community plugins or custom native bridges remains disputed.
- Resolved dispute D1: Whether Unity has first-party or official integrations with major ad networks, such as LevelPlay mediation, while Godot mostly relies on community plugins, is unconfirmed because the checker could not verify it. (The Unity side is settled: LevelPlay officially mediates major ad networks such as AdMob and AppLovin, which is verified. The Godot side is still disputed and is carried forward as a new open dispute.)
