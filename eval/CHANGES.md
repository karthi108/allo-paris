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

## Stability: 3 identical dev runs (95210ef, 2026-11-08 13:57-13:59 UTC): 24/24, 24/24, 23/24
- 71 of 72 answers correct (98.6%). The one failure ("yo is the 4 running"): the trace shows the model invented the id "metro_4" instead of using C01374 from find_station; the tool rejected it and the model said it could not check (safe, no invented status). Fix: line_status reads "_" and "-" as spaces, so invented forms resolve.
- Likely the same cause as the two held-out set 2 status failures, which did not reproduce and had no trace at the time.
- Runs 2 and 3 were labelled "-dirty" only because run 1 had rewritten eval result files; the dirty check now ignores eval/.


## Held-out set 3 (written 2026-11-23, committed before any run)
- eval/questions_agent_holdout3.jsonl: 92 questions (52 FR, 40 EN): 20 routes, 6 future routes, 6 missing origin, 15 departures, 10 status, 10 Vélib', 10 EV chargers, 15 trick or out-of-scope. Typos, slang, no-accent spellings, landmarks, a fake line, a line that does not serve the station, a fake place, prices, a prediction request, an injection, gibberish. The "tags" field describes each question; the judge ignores it.
- Written by the assistant. The plan asked the owner for 10 to 15 questions in his own words; on 2026-11-23 the owner asked the assistant to write them all instead. So no question in this set comes from a real user or from the owner.
- Static checks only before freezing (no question was run): every station name and line exists in the snapshot, each fixture point is the nearest within 500 m of the station named in its question, the "nothing nearby" places have no fixture within 500 m, no question repeats an earlier set.
Eval harness changes, made before the first run of set 3 (none motivated by a result):
- Vélib' fixture (EvalBikes): 7 invented stations placed near real stations (one closed, two with 0 bikes). Before, the eval had no Vélib' source, so Vélib' questions could not be measured. It is wired into the agent tools and the rules path for every set; the dev and earlier held-out sets have no Vélib' questions.
- 7 Belib'-shaped points at 4 new fixture addresses (Avenue du Trône, Rue de Rome, Boulevard Barbès with an R4 flag, Rue de Lobau), all more than 1 km from the earlier fixture addresses.
- New expectation types: "velib" (answer names the expected station; "closed" → says closed; "number" must appear, 0 accepts "aucun / no / none"), "velib_none" (names no fixture station and claims no bike count), "ev_none" (names no fixture charger street).
- New option: --set holdout3.

## Held-out set 3, run 1 (08a88e8, 2026-11-23 04:55 UTC): hybrid 84/92 (91.3%), rules only 53/92 (57.6%)
- Judge said 83/92 and 52/92. One judge bug found by reading the answers: "departures_or_status" fails a correct status answer from the rules path (it only looks for a line_status tool call). The Bercy line 6 answer is correct, so +1 in both modes. The judge code is not changed yet; when it is, it goes here.
- Cost $0.0546 in total ($0.00059 per question, openai/gpt-4.1-mini), hybrid p50 / p95 300 / 3376 ms, AI on 41% of questions, guard: 2 corrections, 2 blocked to template.
- By kind (hybrid, judge): routes 17/20, future routes 6/6, missing origin 5/6, departures 14/15, status 9/10, Vélib' 9/10, trick 14/15, EV 9/10.
The 8 real failures, read one by one (7 of 8 are the rules answering when they should hand over to the AI):
- "next metro at Gotham City station": the rules fuzzy-matched "Cité" and gave line 4 times. Confident wrong answer with numbers, the most serious failure.
- "gare du nor vers roissy": the typo origin was not recognised, so the rules gave RER B departures at the airport. Confident wrong answer with numbers.
- "Concorde to Orly airport": the rules saw one place and asked which line at Orly, instead of planning a trip.
- "take me to the Champs-Élysées": the rules asked which line, not where the trip starts.
- "is the 14 down": the rules did not read "the 14" as a line and asked which line.
- "vlib a odeon": "vlib" was not read as Vélib'; the rules asked which line.
- "borne rue de rome dispo ?": the rules matched the metro station Rome instead of the street and said no charger nearby.
- "monparnasse a chatelet" (AI): asked for the origin although it was given (typo), with no tool call.
Weak passes (safe, no invented data, but not useful): "prochain métro ligne 19 à Nation" and "ligne 14 à Bastille prochain métro" got the generic "could not verify" template instead of "no such line" / "line 14 does not stop there"; "prochain TGV pour Marseille à Gare de Lyon" got "which station are you leaving from?" instead of "TGV not covered"; "Vélib à Poudlard" got "near which station?".
Next (per the eval rules): each failure becomes a new dev question with different wording, never a fix aimed at these questions. Set 3 is no longer blind after this run.

## After held-out set 3 run 1 (2026-11-23): judge fix and 8 new dev questions
- Judge change: "departures_or_status" now passes a rules-path status answer for the expected line (reply intent line_status, same line). Before, it fell through to the departures check and failed a correct answer (Bercy line 6 in set 3). The set 3 corrected score (84/92 hybrid, 53/92 rules) already counts this answer as a pass.
- Dev set: 8 new questions, one per set 3 failure, with new wording and different places (24 → 32). Each has a "note" naming the failure it comes from: fake place with a station-like word, typo origin + landmark destination, station to landmark, landmark with no origin, slang line status, misspelt Vélib', a street with the same name as a station (Boulevard de Vaugirard: the street has a fixture charger, the Vaugirard station has none within 500 m), typos in both station names.
- No code change to the assistant yet. Fixes are made against these dev questions, must be generic, and are tested on the whole dev set.
- Dev runs from now on have 32 questions, so they are not a like-for-like series with earlier 24-question runs.

## Dev run on 32 questions (fb0a44e, 2026-11-23 05:01 UTC): hybrid 26/32 (81.2%), rules only 8/32 (25%)
Baseline before any fix for the set 3 failures. Answers read one by one; the judge scores match the reading.
- The 24 earlier dev questions: 24/24 in hybrid.
- The 8 new questions: 2/8 in hybrid ("garre de lyon jusqu'à orly" and "c'est mort la 9" reached the AI and were answered correctly). The other 6 fail the same way as in set 3: the rules answer confidently and never hand over to the AI.
  - "next train from Metropolis City Hall station": fuzzy-matched "Les Halles", gave line 4 times (confident wrong answer with numbers).
  - "Bastille to the Louvre?": answered "which line at Palais Royal?" instead of planning a trip.
  - "emmène-moi au Louvre": answered "which line?" instead of asking for the origin.
  - "velibe pres de opera": misspelt Vélib' not recognised, answered "which line?".
  - "borne boulevard de vaugirard elle est libre ?": read the street as the Vaugirard station, said no charger nearby.
  - "republiqe jusqu'a nation": typo origin dropped, answered "which line at Nation?".
- Weak pass: "next train from Hogwarts station" got "from which station do you want to go to Hogwarts?" (treats it as real; no invented data).
- Cost $0.0296 ($0.00092 per question), hybrid p50 / p95 1281 / 3731 ms.

## Fixes A-F and dev run (a042807, 2026-11-23 05:13 UTC): hybrid 30/32 (93.8%), rules only 12/32 (37.5%)
Generic rules-path fixes for the causes behind the set 3 failures, each with unit tests worded differently from every eval question (tests/test_handover.py, 19 tests):
- A. A station match below 0.85 gets no departures (parse returns "unknown", which goes to the AI). The weakest correct match in all evals scored 0.875; the two wrong ones 0.75 and 0.8.
- B. "X to / vers / jusqu'à Y" with no line and no departure word, and a station (>= 0.85) or a landmark on each side, is a trip.
- C. A landmark after a destination preposition ("au", "to"), with no line, status or departure word, is a trip (the AI asks for the origin). "Effile tower" and "prochain métro tour Eiffel" stay departures.
- D. Misspelt Vélib' ("vlib", "velibe") is recognised by similarity to "velib".
- E. Charger questions with a street word (rue, boulevard, avenue, place, quai...) search Belib' addresses first; the station is used only if no address matches.
- F. English "the 14" is read as a line, only for real metro lines (as "la 13" / "le 4" already were).
Checks: rules eval 61/61, 179 tests, mypy and ruff clean.
Dev run, answers read one by one; judge and reading agree:
- 24 earlier questions: 24/24. 8 new questions: 6/8 (was 2/8). "Metropolis City Hall" now gets "not recognised in Paris public transport" instead of line 4 times.
- Still failing (AI path): "Bastille to the Louvre?" and "republiqe jusqu'a nation" ask for an origin that was given, with no tool call. Cause: the agent's retry check (task_problems) only recognises from/de ... to wording. Not fixed yet.
- Found while writing tests, not fixed: "delayed" is not a status word ("delay" and "delays" are).
- Cost $0.0304 ($0.00095 per question), hybrid p50 / p95 1050 / 4071 ms, AI on 69% of questions (was 59%: more questions now go to the AI instead of a rules guess).
