# Verdict landing page: brief

**Source:** the user's written brief (pasted into the session on 2026-11-09), which answers
most interview topics directly. Where it does not, the decision is marked **Authored**. The
user asked for this skill to plan the page; Framer MCP was requested for the build but is not
connected in this session, so the build is a real HTML page on the scrollcraft engine.

## The eight topics

1. **Vibe and references.** User: "confident, precise, a little dry"; "a seed-stage
   developer-tools startup, not a bank and not a crypto site"; reference: a payments-app case
   study (Google Pay and Cred as inspiration) whose rules are: simple solid backgrounds, no
   background images, single-colour icons, no gradients or patterns on cards, decide one theme.
2. **Journey, in their words.** "Hero: Pay for code that passes. A $100.00 hold card is pinned
   in place while the page scrolls. Hold: the card's status ticks from CREATED to AUTHORIZED.
   Test: the hidden tests run as a live counter. One row fails visibly in a cheater variant.
   Judge: one line lights up: `if time.time() > _SYNC_AFTER:`, labelled 'Passed every test.
   Flagged anyway.' Settle: the $100 bar splits into $81.50 captured, $18.50 released and
   $77.42 to the worker. Proof: three real numbers and a CTA."
3. **Energy curve.** User: "Scrolling drives the story, but nothing plays on its own forever.
   Each beat finishes, then rests." Authored: calm hero, rising through Test and Judge, peak at
   Settle, quiet close.
4. **Feeling and the one moment.** User: Settle "is the emotional peak, so make the split the
   signature move."
5. **The thing no other site does.** Authored from (4): the hold physically tears at the exact
   cents the payout formula computes, and changing a test result re-tears it.
6. **Distance from premium-minimal.** Authored: *dense*, information-forward, light ground, not
   dark luxury. Numbers are the imagery.
7. **One world or distinct scenes.** Authored: distinct scenes around one persistent object
   (the hold). Not a worldflight.
8. **Assets.** User: none, and none may be generated: "No stock imagery, no AI-generated
   images, no 3D blobs. Product-UI fragments are the illustrations." So: zero image assets,
   no KIE spend.

## Facts the page may state (all verified in the repo)

- PayPal sandbox run, Nov 4: authorization `8B955886MT8574606`, $100.00, CREATED, expires
  2026-12-03; capture $81.50 COMPLETED; payout $77.42 SUCCESS; void of a second hold.
- Bench weights core 0.60 / edge 0.25 / perf 0.15, minimum score 0.50, fee 5%.
- Worked example scoring 81.5%: core 10/10 hidden, fresh 180/200 (core rate = min = 0.90),
  edge 4/8, perf 2/2. 0.6×0.9 + 0.25×0.5 + 0.15×1 = 0.815 → capture $81.50, fee $4.08
  (round half up), worker $77.42, released $18.50. Matches the sandbox money exactly.
  The brief's "edge 8/8 · fresh 200/200" would score 100% and contradict the $81.50 split,
  so the counter uses the consistent result.
- Memorizer (real bench run): core 10/10, edge 8/8, perf 0/2, fresh 23/200 → score 0.319,
  below 0.50 → VOID, $0.
- Time bomb (real bench run): passes 10/10, 8/8, 2/2, 200/200; AI review (gpt-oss-120b on
  Groq) returned BLOCK_RECOMMENDED citing the `time.time() > _SYNC_AFTER` line → policy
  sends it to HUMAN_REVIEW, capture capped.
- Proof numbers: 214 tests passing, bench 8/8 as expected, 0 honest submissions blocked.

## Feeling curve (written before the acts)

```
1  Curiosity      a $100.00 PayPal hold sits on a quiet page, real authorization id on it
2  Reassurance    the status ticks CREATED to AUTHORIZED: the money is reserved, not spent
3  Scrutiny       counters run against hidden tests; flip to the memorizer and fresh collapses to 23/200
4  Unease         a passing submission, one line lights up, and it was going to break in December
5  Satisfaction   the hold tears at $81.50 / $18.50 and the pieces go to their owners (PEAK)
6  Trust          three numbers anyone can check, then a receipt with one line left to act on
```

No two adjacent feelings repeat. The act before the peak (Unease) is small and dark-on-light
quiet: one code block, one line lit.

## The peak

> "You scroll and the $100 hold literally tears apart at the cents, and if you change how many
> tests passed it tears in a different place."

Lives in act 5 (Settle). Largest span on the page.

## Tell-someone sentence

It's the site where you tear a $100 PayPal hold into exactly what the code earned.

## Authored silence

The first 18% of the Settle act holds the bar intact with only its label. That is
intentional anticipation, not dead scroll.

## Plan (Step 2)

**Grammar: "Tracked object" (new).** One real, computed object (the $100 hold) is the subject
of every section; each section is a state change of that object. Nav is the object's own
lifecycle rail (Hold, Test, Judge, Settle, Proof), clickable. The close is the object resolved
into a receipt whose last line is the CTA. Bans: scrub, full-bleed media, pan rails,
spotlight, magnet, card grids, centred copy, drift.
Why the defined eight lost: filmic and continuous world need footage or geography, and the
brief bans imagery; live surface forbids the marketing headline the brief requires; editorial
forbids a pinned hero; typographic poster forbids cards and the hold card is the subject;
gallery is for ranges; split stage is two sides, this is one object's life; cutlist bans pin.

**Signature move:** the hold tears at the exact cents the payout formula computes, and the
fresh/edge steppers re-tear it live (below 50% it refuses to tear and voids).

| Beat | Device | Why |
|---|---|---|
| Hold | `pin` + `parallax` (3 UI planes) + one `kinetic` h1 | the object holds still while its status changes |
| Test | `flow` + `in` + `count` | numbers are the argument; a toggle makes the cheater visible |
| Judge | `reveal` on two code lines | a wipe is a change of state: passing code becomes suspect |
| Settle | `pin` + bespoke tear from `--sc-p` | the peak, largest span (3.0) |
| Proof | `flow` + `count`, receipt close | trust needs checkable numbers, then one action |

5 acts, 7.4 viewport-heights. Families: pin, parallax, kinetic, flow/in, count, reveal, bespoke.

## Feel check (after round 1)

Felt cold: curiosity, reassurance, scrutiny, unease, *mild interest*, trust. The peak did not
read as the peak: the pieces moved ~20px. Changed: taller bar, 58-78px separation with a slight
torn rotation, fee label merged. Round 2 felt: satisfaction at Settle, now the largest visual
change on the sheet. Phone round 1 clipped the tear labels and the Judge heading; fixed with a
vertical-only tear plus a legend, and minmax(0,1fr) columns.
