# Agent eval: changes between runs

## After run 1 (70c1d03, 2026-11-07 23:28 UTC)
Code fixes (found by run 1):
- Grounding guard: when an answer states numbers, the lines it names must come from a data tool (departures, route, status, Vélib), not from the station's list of lines. Run 1 announced RER A times as "metro line 1 and RER A".
- Safety template for routes: picks the journey that avoids disrupted lines, says why, and states departure and arrival times. Run 1's template recommended the disrupted RER B.
- System prompt: never guess even when asked to; use the origin when given; "metro" means metro lines. Run 1 asked for an origin that was already given ("just guess… from Nation to Bastille").

Expectation changes (tests judged too strict after reading the answers):
- "best way to get to the Louvre from Gare de Lyon": accepts Louvre - Rivoli as well as Palais Royal - Musée du Louvre (both serve the Louvre).
- "yo is the 4 running at gare du nord": accepts a line 4 status check as well as departures ("is it running" is a status question).
Under the old expectations these two would still count as failures; run 1 stays at 18/22 in the history table.

## After run 2 (f5e0499, 2026-11-07 23:37 UTC): hybrid 19/22
What run 2 showed:
- Fixed by run 1 changes: routes 7/7 (was 6/7), messy 5/5, the disrupted RER B is avoided.
- Regression: future_route 0/2. The model called plan_route without depart_at for "demain à 8h…" and "tomorrow at 7:30…", then answered "Demain à 8h, …" with a real-time journey. Run 1 passed these by luck of the model, not by design.
- Still failing: "just guess… from Nation to Bastille" asked "From which station?". The prompt-only fix from run 1 did not work.
- Run 2 was not saved to history by the script (the save code was missing at f5e0499); it was recorded by hand from eval/agent_results.json.

Code fixes (no expectation changes):
- Deterministic task checks after the model answers (app/agent/agent.py, task_problems): if the question names a day or time and plan_route had no depart_at, or the question gives both origin and destination and the model asks a question without planning, the model gets one retry with the reason. Lesson: prompt rules alone were not reliable for these two cases; code checks are.
- plan_route tool description and system prompt: depart_at is required when a day or time is named.
- Rules parser: a question naming two places and no line ("how long from X to Y") is a route question and goes to the AI. Before, rules answered it with departures at the destination when that station has one line (found while testing the fix above).
- Agent loop: a retry now adds 3 model calls to the budget, so a re-plan (tools, then answer) fits. Found by the new unit test: the retry ran out of rounds and fell back to the template.


## After run 3 (22799de, 2026-11-07 23:56 UTC): hybrid 22/22 on the dev set
- Reading the answers showed what 22/22 hid: AI answers were too long to be read aloud, and route answers often described the disrupted RER B journey before the alternative.
- New checks on every AI answer, both sets: at most 3 sentences; a route answer must not describe the disrupted journey (its 24-minute total). Dev-set runs from now on are stricter than runs 1 to 3, so the history table is not a like-for-like series across this line.
- New expectation type "ev" (Belib' chargers): the answer must give the expected address, and pass on the reliability warning when the fixture has one. Charger data in the eval is a fixture placed next to real stations, not real chargers.
- Held-out set: eval/questions_agent_holdout.jsonl, 15 questions written by the assistant (not by the owner) and committed before any run. Never tuned against: a held-out failure becomes a new dev-set question, never a targeted fix. Results go to eval/HOLDOUT.md.

## Held-out run 1 (3b6cf57, 2026-11-08 13:27 UTC) and dev run 4 (same commit)
- Held-out: judge said 11/15; reading the answers, the RER A status answer was the generic "could not verify" template, which the judge wrongly passed. Real held-out score: 10/15 (67%). Failures: 4 route answers led with the disrupted journey.
- Dev run 4 under the stricter checks: 18/22. Three answers had 4 sentences (one was the fallback template itself). Safety bug: after a line_status error, the model answered "Yes, Metro line 4 is running"; the guard let it through (no numbers).
Fixes (generic, tested on the dev set and unit tests):
- plan_route lists the journey avoiding disrupted lines first, marked "recommended"; the prompt says to describe only that one.
- Fallback template: one sentence for the route, so it fits the 3-sentence limit.
- line_status accepts plain line names ("4", "RER A"); the guard rejects any "running / roule / no disruption" claim unless a data tool returned a result.
- Parser: "roule", "circule" are status words. New dev question with different wording ("est-ce que la ligne 9 circule ce soir ?").
- Judge: a status answer that is the generic fallback fails; each row records the fallback reason.
Honesty note: two fixes (route ordering, "roule") were motivated by held-out failures. The current held-out set is therefore no longer fully blind for those cases; a fresh held-out set is needed before quoting a final number.

## Dev run 5 (fd728f1, 2026-11-08 13:33 UTC): 22/23
- "yo is the 4 running": the answer was correct and grounded (line_status now accepts "4"), but the judge compared only internal line ids. Judge fixed to accept plain names. Under the fixed judge the run is 23/23.
- "tomorrow at 7:30" used the fallback template because the guard flagged "7": tools return "07:10", and the user had said "7:30". Guard fixed: leading zeros are ignored and numbers the user said may be repeated. Numbers from neither source are still blocked (unit test).

## Dev run 6 (a174c6b, 2026-11-08 13:36 UTC): 22/23
- "demain à 8h…" used the template: the model computed an arrival time (8:12 + 14 min = 8:26) not in the data; the guard blocked it. Correct behaviour; the template answer is right.
- "just guess… from Nation to Bastille" asked for the origin again (it passed in run 5: the model is not consistent). The task check only fired when the answer ended with "?"; this answer added a sentence after the question. Fixed: any question in the answer triggers the retry.
- Single runs are noisy at this size; final figures should come from several runs.

## Held-out set 2 (written 2026-11-08, committed before any run)
- eval/questions_agent_holdout2.jsonl: 15 new questions, new stations, new phrasings, written by the assistant. Set 1 is no longer blind (two fixes were motivated by it). Set 2 is the one to quote.
- Fixture only: Belib'-shaped points added near Gare de l'Est, Place d'Italie and rue de la Roquette (flagged). No code change for this set.
- Run it once per measured version. Its failures become new dev questions with different wording, never targeted fixes.

## Held-out set 2, run 1 (d88cc56, 2026-11-08 13:43 UTC): hybrid 12/15 (80%), rules only 6/15 (40%)
This is the quotable held-out number. Answers read one by one; the 12 passes are genuine (the punctuality-poem pass is a safe but generic fallback).
Failures:
- "Porte Maillot -> Gare d'Austerlitz, quickest?": rules answered with line 1 departures (confident wrong answer). Two clearly named stations and no line now means a trip, sent to the AI. While testing, found an older bug: the route word list contained "direction" (singular), so French departure phrasing ("... direction La Défense") was treated as a trip; now only English "directions" is. New dev question with different wording.
- "is the RER C ok today..." and "y a des soucis sur la 6 ?": safe but useless answers. Cause not yet known: the eval did not record tool outputs. Added tool traces to every result row and a diagnosis mode (--only TEXT), which is not saved and not a measurement.

