# Test fixtures, not real data

These are **test fixtures, not real data**. Hotel names are plausible Dubai names from public knowledge. OSM identifiers, coordinates, distances, availability, tax scenarios, feed validation and evaluation results are invented for testing. They do not establish facts about these hotels or Dubai tax policy. Rates are synthetic. No production component imports this directory.

`node tests/fixtures/generate.mjs` regenerates deterministic JSON and SSE fixtures. `feed.xml` tests download plumbing only; it makes no claim of XSD validity.
