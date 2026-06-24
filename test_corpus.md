# Recommended Test Corpus — Location-Rich Novels on Project Gutenberg

Curated list of novels selected for richness in named, real geographic locations,
suitable as test input for the character location/time extraction pipeline.

Sorted by recommended processing order (progressively harder extraction challenges).
All confirmed available in English on Project Gutenberg as of June 2026.

Dropped from original longlist (per curation): Twenty Thousand Leagues Under the Sea
(#164), Treasure Island (#120), The Adventures of Sherlock Holmes (#1661), Moby Dick
(#2701), The Mysterious Island (#1268), The Jungle Book (#35997), The Prisoner of
Zenda (#95).

---

| # | Title | Author | Gutenberg ID | Notes |
|---|---|---|---|---|
| 1 | Around the World in Eighty Days | Jules Verne | 103 | Primary test book. Explicit in-story calendar, dozens of named cities across four continents, small stable cast. Recommended first. |
| 2 | The Count of Monte Cristo | Alexandre Dumas | 1184 | Marseille, Rome, Paris, Constantinople, Mediterranean. Real dated events. Same structure as #1 but longer and more characters. Recommended second. |
| 3 | The Three Musketeers | Alexandre Dumas | 1257 | Paris, London, La Rochelle, 17th-c. French geography. No absolute dates — good test of book_estimated fallback (Addendum 5). |
| 4 | Five Weeks in a Balloon | Jules Verne | 3526 | Africa continent-crossing journey with richly named geographic stops. Verne universe — potential cross-book meetup with #1. |
| 5 | Robinson Crusoe | Daniel Defoe | 521 | Island, Brazil, Africa, Europe. Fewer locations but unusually precise. Good contrast to the multi-city books. |
| 6 | The Scarlet Pimpernel | Baroness Orczy | 60 | Paris ↔ London ↔ coastal France. Small, consistent location set. Good clean extraction test. |
| 7 | King Solomon's Mines | H. Rider Haggard | 2166 | Named real and fictional African geography. Tests location_type: fictional alongside real. |
| 8 | Adventures of Huckleberry Finn | Mark Twain | 76 | Mississippi River journey. Named American towns and real geography. Good contrast to European-heavy rest of list. |
| 9 | A Connecticut Yankee in King Arthur's Court | Mark Twain | 86 | Real English geography, time-displaced setting. Good temporal edge case for book_estimated. |
| 10 | The Man in the Iron Mask | Alexandre Dumas | 2759 | Same Dumas universe as The Three Musketeers (#3) — overlapping characters and real French locations. Best cross-book meetup potential on this list alongside #2 and #3. |
| 11 | Kim | Rudyard Kipling | 2226 | The Grand Trunk Road across India. Richest in named Indian locations of any book here. Best stress test for Nominatim geocoding outside Europe. |
| 12 | Gulliver's Travels | Jonathan Swift | 829 | Mixed real and fictional geography. Best stress test for location_type: fictional vs. ambiguous handling. Recommended last. |
| 13 | A Room with a View | E. M. Forster | 2641 | Florence → England. Small location set, very precise. Good clean baseline test; contrast to sprawling travel books. |

---

## Recommended processing order

1. **#103** — primary test book, already planned in project brief
2. **#1184** — longer, more characters, still has real dates
3. **#1257** — no absolute dates, tests book_estimated fallback
4. **#2759** — Dumas universe overlap, cross-book meetup test with #2 and #3
5. **#60** — small clean location set, straightforward extraction
6. **#521** — fewer locations, tests precision over variety
7. **#76** — American geography, different extraction character from European books
8. **#86** — temporal edge case, time-displaced setting
9. **#3526** — Africa geography, Verne universe cross-book with #103
10. **#2166** — fictional African geography, tests fictional location handling
11. **#2226** — hardest geocoding test
12. **#2641** — small clean baseline, good for regression testing after schema changes
13. **#829** — hardest location_type edge case, recommended last

## Cross-book meetup potential

- **Dumas universe** (#1184, #1257, #2759): overlapping characters (Athos, Aramis,
  Porthos, D'Artagnan all appear across books), shared French geography, roughly same
  historical era. Will produce the most immediately meaningful meetup results.
- **Verne universe** (#103, #3526): different characters but same genre, overlapping
  real geography (Africa, Indian Ocean). Weaker narrative connection than Dumas but
  geographically compatible.
- **Mark Twain** (#76, #86): different eras and geography — unlikely to produce
  meetups but good for confirming the pipeline correctly finds NO match when there
  shouldn't be one.
