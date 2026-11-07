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

