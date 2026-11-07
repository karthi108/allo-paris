# Agent eval: changes between runs

## After run 1 (70c1d03, 2026-11-08)
Code fixes (found by run 1):
- Grounding guard: when an answer states numbers, the lines it names must come from a data tool (departures, route, status, Vélib), not from the station's list of lines. Run 1 announced RER A times as "metro line 1 and RER A".
- Safety template for routes: picks the journey that avoids disrupted lines, says why, and states departure and arrival times. Run 1's template recommended the disrupted RER B.
- System prompt: never guess even when asked to; use the origin when given; "metro" means metro lines. Run 1 asked for an origin that was already given ("just guess… from Nation to Bastille").

Expectation changes (tests judged too strict after reading the answers):
- "best way to get to the Louvre from Gare de Lyon": accepts Louvre - Rivoli as well as Palais Royal - Musée du Louvre (both serve the Louvre).
- "yo is the 4 running at gare du nord": accepts a line 4 status check as well as departures ("is it running" is a status question).
Under the old expectations these two would still count as failures; run 1 stays at 18/22 in the history table.
