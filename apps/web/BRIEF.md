# Verdict web app: brief

**Self-authored under explicit creative delegation.** The user supplied the eight answers below
(verbatim where quoted) and delegated the remaining decisions. Authored decisions are marked.

## The eight topics
1. **Vibe**: "precise, calm, trustworthy, a little dry". References: "a bank statement printed on
   good paper, Swiss railway timetables, the Stripe Press books, a referee's whistle".
2. **Journey**: "land on Home and understand 'PayPal holds it, we test it, PayPal pays only what
   passed' in one scroll → log in as a role → post or take a job → watch the verdict settle →
   check the signed receipt".
3. **Energy**: "calm on Home and forms; the one intense moment is the verdict settling".
4. **Feeling**: "curiosity (Home) → control (posting/funding) → suspense (grading progress) →
   relief and fairness (the hold splits) → trust (receipt verifies)".
5. **Only-here**: "the $100 hold bar physically tears at the computed cents into worker / fee /
   back-to-buyer, using the real numbers from the API".
6. **Range**: "premium-minimal with an editorial, numbers-first feel".
7. **Structure**: "distinct screens, not one continuous world".
8. **Assets**: none. Type, numbers, hairlines and the hold bar are the visuals.

## Evidence vs assumption
- Numbers on Home come from a real hosted run (Render, PayPal sandbox, Nov 10): the
  `honest_partial` submission scored 75.1% (fresh 188/200), PayPal captured $75.15, paid the
  worker $71.39, fee $3.76, released $24.85. Nothing else is quoted as a figure.
- Everything on the verdict page is live from `GET /submissions/:id` and `GET /receipts/:job`.

## Grammar (authored)
**Working surface with one told story.** The app is a tool; only Home carries a scroll story
(one pinned act), and only the verdict page carries the peak. Forms and tables never move under
the reader. Filmic one-shot, worldflight, gallery and chapters lost because the user asked for
distinct screens and a calm tool; the landing page already owns "tracked object".

## Journey (Home)
1 Recognition: "who pays first" is the question on screen.
2 Turn: the $100 is held, not charged.
3 Substance: tested, judged.
4 Resolution: the hold splits at real cents.
5 Commitment: the open-jobs table, the one action is "Try it".

## Feeling curve
| Act | Feeling | Cause |
|---|---|---|
| Home intro | curiosity | one plain claim, nothing moving |
| Home story (pinned) | understanding, then fairness | the same hold card changes state under the reader's scroll: held → tested → judged → split → signed |
| Home table | agency | live open jobs, a real thing to click |
| Post / fund | control | quiet form, validation report, PayPal button |
| Grading | suspense | the progress rail runs, the pill pulses |
| **Verdict settles** | **relief and fairness (the peak)** | the live hold tears at the computed cents |
| Receipt | trust | the card slides in; "Check the signature" says Valid |

**Authored silence**: on the verdict page the bar sits whole for 450ms after the verdict arrives
before it tears, so the reader sees what was held before it splits.

## The peak
"The $100 bar literally broke apart into what the worker got and what went back to me."
Lives on `/submissions/:id`.

## Tell-someone sentence
It's the site where you watch your PayPal hold split at the exact cents your code earned.
