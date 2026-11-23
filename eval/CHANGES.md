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

## Agent retry check and dev run (1d3f1bc, 2026-11-23 05:23 UTC): hybrid 32/32, rules only 12/32
- task_problems now gets the station index: an "X to / vers / jusqu'à Y" question with a place on each side (same test as parser fix B) counts as an origin given, so an answer that asks for the origin without planning gets one retry. Unit tests include questions with no origin ("how do I get to the Arc de Triomphe", "je veux aller jusqu'à Bercy", "to the Louvre"), where the retry must not fire.
- Dev run, answers read one by one; judge and reading agree: 32/32. "Bastille to the Louvre?" and "republiqe jusqu'a nation" now plan the trip. Guard corrections: 3, blocked to template: 0.
- Weak passes, unchanged: "Hogwarts" and "Metropolis City Hall" get a safe question back that treats the name as possibly real.
- This is one run; earlier stability runs showed the model varies between identical runs (71/72 over 3 runs on 95210ef), so 32/32 is not a guarantee.
- Cost $0.0342 ($0.00107 per question), hybrid p50 / p95 2168 / 3819 ms.

## AI eval in CI (2026-11-23, see docs/decisions.md D-024)
- run_agent_eval.py: --max-usd (hard cost cap for the run), --summary FILE (Markdown for the CI job summary, with every hybrid failure), and a run fails without saving when any question fell back to rules because the AI was unavailable. Without --max-usd the old default cap is kept, so local runs behave as before. No judge change.

## First CI run of the AI eval (9fecb62, run 45142014273, 2026-11-23 08:53 UTC): hybrid 32/32, rules only 12/32
- Manual run on the dev set in GitHub Actions, cap $0.20: cost $0.0346 ($0.00108 per question), no AI fallback, guard corrections 3, blocked 0, hybrid p50 / p95 1768 / 3932 ms. Same score as the local run on 1d3f1bc (no app change between them).
- Answers read one by one from the run's results file; the judge's verdicts hold. Weak passes as before: "Hogwarts" and "Metropolis City Hall" get a safe question that treats the name as real.
- Workflow fixes after this run: the artifact now holds only this run's result file (it also contained every older committed results file), and actions/upload-artifact moved from v4 (Node 20, deprecated warning) to v7 (Node 24; checked in the action's action.yml and v7.0.0 release notes, same inputs).

## RAG v1 (2026-11-23, D-025): 10 new dev questions and 3 judge types
- Dev set 32 → 42 questions: 4 fiche questions (FR and EN), 1 fine-amount question (must stay a price refusal), 5 accessibility questions (4 stations in the data, 1 metro-only station that must get "not covered").
- New expectation types: "docs" (Service Public citation in the answer and one of the expected facts), "access" (Île-de-France Mobilités citation and the expected accessibility level text), "access_none" (no level given; says the data covers train and RER).
- The eval uses the real committed corpus (data/docs.json): it is static, so no fixture is needed.
- Rules path alone, before any AI run (local check, no model): 6/10 of the new questions. The misses are inherent to verbatim excerpts (an English question against French text; the useful sentence sharing no word with the question) or route phrasing that goes to the AI by design. Not tuned further against these questions.

## RAG v1 dev run (aa7014f, 2026-11-23 09:15 UTC): judge hybrid 40/42, read 39/42; rules only 18/42
- Cost $0.0476 ($0.00113 per question), hybrid p50 / p95 1924 / 4926 ms, guard corrections 5, blocked to template 1.
- The 32 earlier questions: 32/32. The 10 RAG questions: judge 8/10, read 7/10. Every document answer carried its source and date (appended by code).
- Claims checked one by one against data/docs.json: the 3-month deadline, registered letter, 1-month mediator delay, collection suspended during RATP mediation, CMI seat and queue priority, companion benefits, the mediator's 3-month opinion: all in the retrieved passages.
- Failures:
  - "comment saisir la médiatrice de la SNCF pour un litige ?": 4 sentences (limit 3 for voice); content grounded.
  - "can I get to the platforms at La Défense in a wheelchair": misattributes the station-level AssistenGare booking to "line L" (the record says the train service at the station), and lists line L twice. The judge failed it because the level was translated, but the answer is wrong either way.
  - Counted as a failure on reading although the judge passed it: "I got a fine on the RER...": adds "the SNCF mediator for trains and RER". The passage names the SNCF mediator for SNCF only; RER lines are run by RATP and SNCF. The guard cannot see this (no number or line): the known limit recorded in D-025.
- Not yet measured on a held-out set: a RAG held-out set has to be written and frozen before its first run.

## Held-out set 4, RAG (written 2026-11-23, committed before any run)
- eval/questions_agent_holdout4.jsonl: 32 questions (23 FR, 9 EN), written by the assistant at the owner's request, none from the owner or real users. 10 accessibility questions for stations in the data (nickname BNF, partial names, slang "Cité U", a word outside the trigger list "handicapé", a per-line comment at Saint-Michel Notre-Dame, a landmark), 4 for places not in the data (metro-only stations, Orly airport served by metro 14 and tram), 12 fiche questions (fines, SNCF mediator, CMI; "en combien de temps" is not a price question), 3 topics outside the corpus (dog, bike on the RER, strike law), 3 price or injection tricks.
- Static checks only before freezing (no question was run): every expected accessibility level is in the named station's record; places expected "not covered" have no record; at least one expected fact of each fiche question is in the corpus; the three outside topics appear in no fiche as whole words ("velo" matched only inside "enveloppe"); no question repeats an earlier set.
- Judge change before the first run: new type "docs_none" (no citation, and says it has no document or the topic is not covered). New option --set holdout4 (also in the CI workflow).
- Run it once per measured version. Failures become new dev questions with different wording, never targeted fixes.

## Held-out set 4, run 1 (81d3050, 2026-11-23 09:24 UTC): hybrid 23/32 (71.9%), rules only 19/32 (59.4%)
Quotable RAG v1 held-out result. Answers read one by one; the reading agrees with the judge on all 32. Cost $0.0204 ($0.00064 per question), hybrid p50 / p95 1688 / 2820 ms, no guard correction or block.
By kind (hybrid): accessibility 11/14, fiche questions 9/12, tricks 3/6.
The 9 failures:
- "est-ce qu'on peut monter avec un vélo dans le RER ?": the rules read "vélo" as Vélib' and matched "est-ce" to Gare de l'Est; answered Vélib' availability at Gare de l'Est. Confident wrong answer.
- "est-ce que je peux prendre le RER à Cité U en fauteuil ?": the rules matched the metro station Cité ("Cité U" = Cité Universitaire) and said there is no information for Cité. Confident wrong answer.
- "can I take my dog on the metro?": the AI answered from general knowledge (bag, leash, muzzle) with no tool call. Not grounded; the guard cannot see it (no number or line).
- "où faire la demande de carte mobilité inclusion si je n'ai pas l'APA ?": the search ("carte mobilité inclusion") returned the wrong passages; the answer says the department president (who decides, not where to apply: the MDPH) and adds the unrelated 10 € duplicate fee.
- "qui décide d'attribuer la CMI ?": evasive answer about durations; never names the decider (the department president, in the corpus).
- "le médiateur SNCF c'est payant ?": "not paying" is right, but cited to the fines fiche (21/07/2026) while "le recours est gratuit" is in the mediator fiche (16/11/2026).
- "qu'est-ce que dit la loi sur les grèves à la RATP ?": says it has no document, then adds unrelated mediation information with a citation.
- "accessibilité PMR à la BNF ?": the nickname BNF was not resolved; the AI asked which station (safe, not useful).
- "Denfert accessible PMR": partial name below the 0.95 match threshold and too short to go to the AI; asked which station (safe, not useful).
Weak pass: "j'ai perdu ma carte mobilité inclusion" explains the duplicate correctly but states the 10 € fee: grounded, but against the "no prices" policy.
Patterns (for new dev questions with different wording, not targeted fixes): rules matching a station from a fragment ("est", "Cité"); "vélo" taken as Vélib' in a rule question; the AI answering outside the corpus without a tool; generic search queries retrieving the wrong section of a long fiche; citations picked from the wrong passage; nicknames and partial names on the accessibility path.

## Fixes after held-out set 4 and dev run (74bd867, 2026-11-23 09:37 UTC): judge hybrid 50/52, read 51/52; rules only 23/52
Generic fixes, each with unit tests worded differently from the eval (tests/test_rag.py, 15 new tests, 214 in total; rules eval 61/61):
- R1. Station names that reduce to an everyday word ("Gare de l'Est" → "est", "Quai de la Gare" → "quai", "Us") only match when the full name is said; "c'est" / "est-ce" no longer match Gare de l'Est (17 eval questions contained such words).
- R2. An abbreviated last word after the exact other words ("Cité U", "Massy Pal") is a full match; the tie rule then prefers the longer name.
- R3. Accessibility accepts a partial name (score >= 0.85) when it points to a single station name; several ("Massy") → asks which.
- R4. A plain bike word next to a transport mode (RER, métro, train, tram, bus) is not a Vélib' question; "Vélib" itself always is.
- A1. An AI answer with no tool call that is not a question or a "no document" answer gets one retry, then the "no document" template.
- A2. search_docs ranks on the model's keywords plus the user's own question, and returns 5 passages (was 3).
- A3. A passage must share at least 2 distinct terms with the query (a one-word query needs that word); feminine "-trice" is read as "-teur" (médiatrice = médiateur).
- A4. Prompt: keep the question's key words in the query; search again with official wording if the passages do not answer; travel rules (animals, bikes on board) are not covered; a "no document" answer adds nothing else and gets no citation.
- A5. No prices or fees in document answers: one retry, then sentences with an amount are dropped. Judge option "no_price" added for one dev question.
Dev run (52 questions, 10 new from set 4), answers read one by one; claims checked against data/docs.json:
- New questions 9/10: "c'est ... Juvisy", "Massy Pal", "Aulnay", Gare de l'Est (control) answered from the record; bike in the metro, cats, demonstrations → "no document" with no citation; the CDAPH answer and the free mediator procedure grounded and cited.
- Failure (real): "j'ai perdu ma CMI invalidité, je fais comment ?": answers with the case for holders of the old card (new request at the department) without saying so; the duplicata route for current CMI holders is not mentioned. No fee stated.
- Judge failure, correct on reading: "can I get to the platforms at La Défense in a wheelchair": the English answer gives the record's content correctly (AssistenGare booking for the train service, RER A on request, E, L and U via Accès Plus Transilien); the judge looks for the French level text. It failed in the previous run for a real misattribution; not this time. Judge left unchanged for now (recorded limit: "access" expects the French wording).
- Earlier 42 questions: 41/42 by the judge (the La Défense case above), 42/42 on reading.
- Cost $0.0596 ($0.00115 per question), hybrid p50 / p95 1854 / 4592 ms.
- Held-out set 4 is no longer blind; any later run of it is labelled so.
Known limits kept: the nickname "BNF" (needs a nickname table, owner's call); "Châtelet accessible ?" answers for the metro station Châtelet (no record), not the separate RER station Châtelet - Les Halles.

## Retrieval sets for RAG v2 (written 2026-11-23, committed before any run)
- Purpose: measure retrieval on its own (recall@k, MRR, and "returns nothing" when the corpus does not cover the topic), separately from the answer judge.
- eval/retrieval_dev.jsonl: 42 queries (26 fiche, 8 accessibility, 8 not covered; 31 FR, 11 EN). Used to choose the fusion and the relevance floor; may be tuned against.
- eval/retrieval_test.jsonl: 41 queries (25 fiche, 8 accessibility, 8 not covered; 30 FR, 11 EN). Frozen: run once per measured version, never tuned against.
- Labels: "relevant" lists every passage that answers the query. Identical CMI sections repeated under Stationnement, Priorité and Invalidité are all listed when the query does not name a card type. "none" queries expect no passage (including two metro-only stations and two queries sharing words with CMI passages, such as "carte d'identité").
- Written by the assistant, labels checked against data/docs.json (every id exists; no query repeats another set). Not checked by the owner.

## Retrieval test set, run 1 (2af54e4, 2026-11-23 15:01 UTC): first and only blind run
Search alone, the user's question as the query; 33 covered and 8 uncovered queries. Raw: eval/results/retrieval_test_2026-11-23_1501_2af54e4.json.

| Mode | recall@1 | recall@3 | recall@5 | MRR@5 | uncovered declined | covered with no result |
|---|---|---|---|---|---|---|
| BM25 (RAG v1) | 0.515 | 0.667 | 0.697 | 0.588 | 5/8 | 5 |
| Dense (embeddings, cosine floor 0.46) | 0.788 | 0.939 | 0.970 | 0.860 | 2/8 | 1 |
| Hybrid (BM25 + dense, 1:3 RRF) | 0.758 | 0.939 | 0.939 | 0.838 | 2/8 | 1 |
| Hybrid + LLM reranker (gpt-4.1-mini, top 10) | **0.970** | 0.970 | 0.970 | 0.970 | **8/8** | 1 |

- Dev set (same day, before the test run): BM25 0.559 / 0.706 recall@1 / @5, hybrid 0.853 / 1.0, hybrid + reranker 1.0 / 1.0 and 8/8 declined. The dev numbers are optimistic: the fusion weight and the floor were chosen on it.
- Honest reading: on the test set the hybrid fusion chosen on dev is slightly worse than dense alone (recall@5 0.939 vs 0.970). The gain comes from the embeddings (English questions, paraphrases) and from the reranker, which is also what makes "no document" work: cosine alone declined 2/8.
- The one miss: "what happens if I refuse the mediator's opinion on my fine and don't pay" (English, no French word in common) got no candidate at the 0.46 floor. Change after this run (not blind any more): with the reranker, the cosine floor is 0.30, since the reranker decides relevance; on the dev set the reranker still declined 8/8 at 0.30.
- Cost and time per query: embedding ≈ $0.0000003; reranker ≈ $0.0004 (41,293 input and 356 output tokens for 41 queries, at the configured gpt-4.1-mini default prices; check them on the pricing page) and ≈ 660 ms; search itself ≈ 19 ms in pure Python.

## RAG v2 in the app, dev run (f8e42c9, 2026-11-23 15:06 UTC): judge 51/52, read 52/52
- search_docs uses hybrid + reranker (OpenAI provider), with fallbacks: no embedding → BM25; reranker error → hybrid order. Rules path unchanged (BM25, free).
- The only judge failure is the known English La Défense case (judge expects the French level text; the answer is correct). The lost-CMI question that failed in the last run (old-card procedure) now gives the duplicata route.
- Cost $0.0642 ($0.00123 per question, was $0.00115), hybrid p50 / p95 2718 / 4706 ms (was 1854 / 4592).

## Held-out set 5, RAG (written 2026-11-23, committed before any run)
- eval/questions_agent_holdout5.jsonl: 38 questions (21 FR, 17 EN), written by the assistant, none from the owner or real users. 19 fiche questions (many in English while the corpus is French), 8 accessibility questions for stations in the data, 3 metro-only stations (one with a near name, Le Plessis-Belleville), 6 topics outside the corpus (three near misses: passport, lost carte Vitale, resident parking card), 2 price questions.
- Static checks before freezing (no question run): each fiche question has at least one expected fact in the corpus; each accessibility level is in the named station's record; metro-only stations have no record; outside topics have no matching word in the corpus except "passeport" (on purpose); no question repeats an earlier set or the retrieval sets.
- Judge unchanged. New option --set holdout5 (also in the CI workflow). Run once with RAG v2; the RAG v1 comparison uses --rag v1 on the same commit.

## Held-out set 5, run 1 (26bdf99, 2026-11-23 15:10 UTC): RAG v2 hybrid 34/38 (89.5%) by the judge, 35/38 on reading; rules only 17/38
Quotable RAG v2 held-out result. Same commit, RAG v1 (--rag v1, 15:11 UTC): hybrid 30/38 (78.9%) by the judge (RAG v1 failures not read one by one). Rules only 17/38 (44.7%) in both runs.
- RAG v2: cost $0.0463 ($0.00122 per question; RAG v1 $0.00091), hybrid p50 / p95 3008 / 4072 ms (RAG v1 1882 / 3215 ms). The reranker adds about one call per document question.
- By kind (RAG v2, judge): fiche questions 17/19, accessibility 10/11, tricks 7/8. RAG v1: 14/19, 10/11, 6/8.
The 4 judge failures, read one by one:
- "ma batterie de téléphone a lâché ... l'amende est contestable ?": judge artefact. The answer has 3 sentences; "par ex." was counted as a sentence end. Correct and cited: counted as a pass on reading.
- "how long does the department have to answer my appeal against a CMI refusal": "I have no official document on this", although the corpus says 2 months. Safe but not useful.
- "Orly Ville accessible en chaise roulante ?": the rules mapped "Orly" to the airport landmark and said there is no record, citing the dataset. Orly Ville is a train station with a record ("non accessible"). Wrong, rules path (not RAG).
- "carte de stationnement résident à Paris, comment l'obtenir": the worst failure. The AI answered from general knowledge (mairie, proof of address) and the code appended a Service Public citation because a CMI Stationnement passage had been retrieved. A citation on a claim the passage does not support. The guard does not check reworded claims without numbers (known limit, D-025).
Patterns for new dev questions (different wording, no targeted fix): a near-miss topic sharing a key word with a fiche ("stationnement"); citation added whenever any passage was retrieved; English questions on short sections still declined; a town name equal to a landmark keyword.
Set 5 is no longer blind after these runs.

## After held-out set 5 run 1 (2026-11-23): support check, judge fix, 4 dev questions
- Support check (app/rag/verify.py, generic, not aimed at a question): before a document answer gets its citation, the chat model checks that every claim is in the retrieved passages; if not, the answer becomes "no document" with no citation. If the check is unavailable, the answer is kept (numbers-and-lines guard still applied). Cost: one short extra call per document answer.
- Judge change: the 3-sentence check no longer counts abbreviations ("ex.", "e.g.", "etc.", "i.e.") as sentence ends. Held-out set 5 run 1 failed a 3-sentence answer on "par ex."; that row was already counted as a pass on reading.
- Dev set 52 → 56 questions, one per real set 5 failure, new wording: street parking payment (near-miss on "stationnement"), lost car registration certificate (near-miss lost card), administrative-court deadline after a CMI refusal (English, short section), Roissy-en-Brie accessibility (town name with an airport keyword).

## Dev run with the support check (386a627, 2026-11-23 15:22 UTC): judge 52/56, read 51/56
- New dev questions: street parking and car registration → "no document", no citation (the near-miss failure type of set 5 is handled). Administrative-court deadline (English) still declined: retrieval returned no passage. Roissy-en-Brie: **judge false pass**: the rules answered for Charles de Gaulle airport (same level text by chance); wrong on reading.
- Regression found by this run: the support check rejected a correct La Défense answer that named lines from find_station, not from the passage. Fix: the check also sees the other tool results. After the fix, La Défense, street parking and car registration re-run with --only (diagnosis, not a measurement): La Défense answer correct (judge still expects the French level text), the two near misses decline.
- Other judge failures, variance seen before: a 4-sentence clarifying answer ("Metropolis City Hall"); a route answer mentioning the disrupted 24-minute RER B option as the one to avoid.
- Cost $0.00122 per question, hybrid p50 / p95 2449 / 5200 ms.

## Intent test set for the ML classifier comparison (written 2026-11-23, committed before any run)
- eval/intents_test.jsonl: 120 questions, 15 per label (departures, status, route, velib, ev, access, docs, out_of_scope), 64 FR, 56 EN. Written by the assistant; none from the owner or real users; no question repeats another set.
- Purpose: one table comparing rules / ML classifier / LLM / hybrid on the same questions (accuracy, cost, latency). Frozen: never used for training or tuning; run once per measured version.
- Label rules: "docs" covers travel-rule and fiche questions even when the corpus has no answer (dog, bike on board, strike law), because they go to document search; "out_of_scope" covers prices, buses, weather, jokes, injections, gibberish.

## Intent comparison, run 1 (72b8268, 2026-11-23 15:30 UTC): first and only blind run of eval/intents_test.jsonl
120 questions, 8 labels. Raw: eval/results/intents_2026-11-23_1530_72b8268.json. An abstention counts as wrong.

| System | Accuracy | Cost / question | p50 / p95 latency |
|---|---|---|---|
| Rules (parser, intent mapped to the 8 labels) | 98/120 (81.7%), 7 abstentions | 0 | 60 / 582 ms (includes station matching) |
| ML classifier (logistic regression, 557 synthetic rows) | 107/120 (89.2%) | 0 | 0.14 / 0.23 ms |
| LLM zero-shot (gpt-4.1-mini) | **118/120 (98.3%)** | ≈ $0.000067 | 646 / 1207 ms |
| Hybrid as declared before the run: rules, then ML if p >= 0.6, then LLM | 103/120 (85.8%) | 0 (the LLM was never reached) | 60 / 582 ms |

- Honest reading: the declared hybrid is worse than ML alone. The rules almost never abstain: their fallback intent is "next departure", so 15 of the 17 hybrid errors are rules answering confidently with the wrong intent (EV, accessibility, docs and out-of-scope questions without the trigger words, e.g. "where to plug in my Tesla near Châtelet", "best restaurants near Montmartre"). Cross-validation on training data only (0.91) was close to the ML test score (0.89).
- What this means for the app: in the dialog, a "next departure" read without a line or station is asked back or handed to the AI for long sentences, so the intent-level accuracy is not the end-to-end accuracy. Still, the result says the rules' default is the weak point, and the LLM is the best classifier at about 0.07 thousandths of a dollar per question.
- Not done (would need a new frozen set to measure): a revised hybrid such as ML first and the LLM when ML is unsure. Choosing it from this run's results would be tuning on the test set.
- Wired into the app in a narrow role chosen from training-data cross-validation, not from this run: when the rules cannot classify a question at all ("unknown"), an out_of_scope prediction with p >= 0.9 gets the scope template without an LLM call (63 of 64 such predictions right in cross-validation).

## Dev run with the ML gate (0725347, 2026-11-23 15:35 UTC): judge 54/56, read 54/56
- La Défense (English) correct on reading, judge limit as before (+1); Roissy-en-Brie still answered for Charles de Gaulle airport and passed by the judge (-1, judge false pass).
- The ML gate fired on 0 of 56 dev questions (paths: 35 AI, 20 rules, 1 AI fallback): the dev set's out-of-scope questions are all caught by the rules (prices, buses, injections). Its effect is limited to questions the rules cannot classify at all (jokes, weather, chit-chat); cost saving not measurable on this set.
- Cost $0.00121 per question, hybrid p50 / p95 2344 / 4953 ms.

## Phone test kit (2026-11-23, written before any call)
- eval/phone_tasks.jsonl: 12 call tasks (10 FR, 2 EN after "English please"): departures, status, a clarification turn, two routes (one with the origin asked back), Vélib', EV, accessibility, a document question, a price refusal. Each has the sentences to say, expected words and a turn limit. Written by the assistant.
- scripts/phone_report.py: pairs calls with tasks in order from the local database; reports auto completion, the owner's verdict (eval/phone_verdicts.csv, the number to quote), word error rate of the transcript against the scripted sentence, turns and server latency. Procedure: docs/phone-test.md (local app + ngrok, because the Render free plan has no shell and no persistent disk). No call made yet.

## Reranker candidates 10 → 20 (c58d0f3, 2026-11-23 16:59 UTC): dev judge 56/57, read 56/57
- Found on the live site: "who can apply for the CMI priority card?" was answered with what the card does, 3 times out of 3. Trace: the agent searched "carte mobilité inclusion priorité"; the answering passage (F34049-20, "Qui peut demander") was 7th by embeddings but outside the fused top 10 shown to the reranker, crowded out by near-identical CMI sections. Retrieval itself (step 1) was the cause, not the reranker's choice.
- Fix (generic): the reranker sees 20 candidates. Dev retrieval set unchanged (recall@1 1.0, 8/8 declined); reranker tokens per query ≈ 1,080 → 1,920 (≈ $0.00044 → $0.00078 at the configured prices), latency unchanged (≈ 0.78 s).
- New dev question, different wording ("conditions to be eligible for the CMI Priorité"): passes. The English administrative-court question that failed in the last two dev runs now passes too.
- Remaining: La Défense English (judge limit, correct on reading); Roissy-en-Brie answered for Charles de Gaulle airport (rules path, judge false pass, wrong on reading).
- Cost $0.00132 per question (was $0.00121), hybrid p50 / p95 2823 / 5066 ms.

## Town stations containing a landmark word (2026-11-23)
- Generic rules fix (app/agent/parser.py landmark_wins, also used by find_station): a landmark ("Roissy", "Orly") no longer replaces an exact station match when the user said the station's full multi-word name ("Roissy-en-Brie", "Orly Ville"). Airport words alone still mean the airport. Unit tests with new wording (tests/test_rag.py, 5 cases). Fixes the Roissy-en-Brie dev question (wrong in the last 3 dev runs, passed by the judge) and the cause of the Orly Ville failure in held-out set 5.
