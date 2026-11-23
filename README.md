# Allô Paris · EV charger history (ev-data branch)

Status history of the Paris public EV charging network Belib', collected every 10 minutes since 2026-11-08 by the Allô Paris project (GitHub Actions workflow `ev-collect.yml` on `main`).

## Source and licence
- **Source:** Ville de Paris, open data portal, dataset "Belib' - Points de recharge pour véhicules électriques - Disponibilité temps réel" (opendata.paris.fr, dataset id `belib-points-de-recharge-pour-vehicules-electriques-disponibilite-temps-reel`).
- **Licence of the source:** Open Database License (ODbL) 1.0.
- **Licence of this database:** the files on this branch are a database derived from that dataset and are made available under the same **Open Database License (ODbL) 1.0**: https://opendatacommons.org/licenses/odbl/1-0/ . Any public use must credit "Ville de Paris" as the source and keep derived databases under the ODbL.
- Independent project, not affiliated with or endorsed by the City of Paris or the Belib' operator.

## Files
- `points.csv`: charge points seen (id, address, district, coordinates, first seen).
- `state.csv`, `snapshots.csv`, `events/`: status changes and snapshot times as observed by the collector (a change is dated when the collector saw it, up to 10 minutes late).
- `flags.json`: reliability flags from rules R1 to R4 (provisional thresholds), used by the Allô Paris app.

Collection gaps are recorded, never filled. Method and limits: README and docs/decisions.md (D-021 to D-023) on the `main` branch.
