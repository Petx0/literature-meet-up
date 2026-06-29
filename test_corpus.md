# Recommended Test Corpus — Location-Rich Novels on Project Gutenberg

Curated list of novels selected for richness in named, real geographic locations,
suitable as test input for the character location/time extraction pipeline.

Sorted by recommended processing order (progressively harder extraction challenges).
All confirmed available in English on Project Gutenberg as of June 2026.

Dropped from original longlist (per curation): Twenty Thousand Leagues Under the Sea
(#164), Treasure Island (#120), The Adventures of Sherlock Holmes (#1661), Moby Dick
(#2701), The Mysterious Island (#1268), The Jungle Book (#35997), The Prisoner of
Zenda (#95), Kim (#2226).

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
| 11 | Gulliver's Travels | Jonathan Swift | 829 | Mixed real and fictional geography. Best stress test for location_type: fictional vs. ambiguous handling. Recommended last. |
| 12 | A Room with a View | E. M. Forster | 2641 | Florence → England. Small location set, very precise. Good clean baseline test; contrast to sprawling travel books. |
| 13 | War and Peace | Leo Tolstoy | 2600 | Napoleonic Wars (1805–1812), real dated battles (Austerlitz, Borodino), huge cast, Moscow/St. Petersburg/Vienna geography. Strongest time-anchoring test in the set. Likely exceeds MAX_CHAPTERS, auto-skipped like Les Misérables. |
| 14 | Anna Karenina | Leo Tolstoy | 1399 | Russia (Moscow, St. Petersburg, countryside estates), real contemporary timeframe. Likely exceeds MAX_CHAPTERS, auto-skipped. |
| 15 | Crime and Punishment | Fyodor Dostoevsky | 2554 | St. Petersburg street-level geography, action compressed into days — tests fine-grained day/neighbourhood matching vs. the corpus's usual sprawling, multi-year stories. |
| 16 | Notre-Dame de Paris (The Hunchback of Notre Dame) | Victor Hugo | 2610 | Medieval Paris (1482), real landmarks — contrasts with Hugo's own Les Misérables (1815–1832 Paris) already in the DB for a same-author/same-city, different-era test. |
| 17 | Ben-Hur | Lew Wallace | 2145 | 1st-century Roman Empire/Judea, Mediterranean-spanning real geography — pushes the corpus's time range far earlier than anything currently in the DB. |
| 18 | The Last Days of Pompeii | Edward Bulwer-Lytton | 1565 | Pompeii, 79 AD — eruption date is a fixed historical anchor, about as precise a real-world time/location test as exists in literature. |
| 19 | Quo Vadis | Henryk Sienkiewicz | 2853 | Ancient Rome under Nero — same era family as Ben-Hur/Pompeii, different city focus (Rome itself). |
| 20 | Middlemarch | George Eliot | 145 | Real Midlands England region, large ensemble cast, real 1830s political backdrop (Reform Act). |
| 21 | The Mayor of Casterbridge | Thomas Hardy | 143 | Dorset/Wessex English geography, smaller cast — clean baseline test. |
| 22 | The Age of Innocence | Edith Wharton | 541 | 1870s New York high society — first Gilded Age American setting in the corpus. |
| 23 | The Adventures of Tom Sawyer | Mark Twain | 74 | Selected for popularity + Wikidata character coverage (third batch, see below), not location-richness — thinner geography than the rest of this list. |
| 24 | Treasure Island | Robert Louis Stevenson | 120 | Re-added under the third batch's different criteria below despite being explicitly dropped from the original longlist (line 10) for thin location variety — included here for its Wikidata-sourced main-cast coverage and popularity, not as a location test. |
| 25 | A Study in Scarlet | Arthur Conan Doyle | 244 | London-centric detective fiction; thinner geography than the rest of this list — selected for popularity + Wikidata coverage, not location-richness. |
| 26 | Ulysses | James Joyce | 4300 | Dublin, single-day timeframe — selected for popularity + Wikidata coverage; a real stress test for the book_estimated/day-precision machinery given its compressed timeframe. |
| 27 | A Portrait of the Artist as a Young Man | James Joyce | 4217 | Ireland, multi-year Bildungsroman — selected for popularity + Wikidata coverage. |

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
11. **#829** — hardest location_type edge case
12. **#2641** — small clean baseline, good for regression testing after schema changes

## Second batch (added 2026-06-26)

13. **#2554** — Crime and Punishment — fine-grained day/neighbourhood time test
14. **#2610** — Notre-Dame de Paris — same-city/different-era contrast with Les Misérables
15. **#2145** — Ben-Hur — ancient-world cluster, earliest time range in the corpus
16. **#1565** — The Last Days of Pompeii — ancient-world cluster, fixed historical date anchor
17. **#2853** — Quo Vadis — ancient-world cluster, Rome focus
18. **#145** — Middlemarch — large-cast English contrast to Austen/Brontë
19. **#143** — The Mayor of Casterbridge — clean small-cast English baseline
20. **#541** — The Age of Innocence — first Gilded Age American setting
21. **#2600** — War and Peace — strongest time-anchoring test; likely skipped by MAX_CHAPTERS
22. **#1399** — Anna Karenina — likely skipped by MAX_CHAPTERS

War and Peace and Anna Karenina are ordered last because, like Les Misérables,
their Gutenberg editions split into hundreds of short chapters and will likely
be auto-skipped by the `MAX_CHAPTERS=120` guard in `run_test_corpus.py` — no
API cost incurred, consistent with existing Les Misérables handling.

## Third batch (added 2026-06-29)

Different selection criteria from the rest of this file: chosen for Gutenberg
popularity (download count) and confirmed Wikidata `P674` main-character
coverage - to exercise `TARGET_CHARACTERS_AUTO_DISCOVER` (see
`literature_meetup/model_config.py`) on real, non-hand-picked books - not for
geographic richness like batches one and two. Also filtered to exclude
fantasy/sci-fi and supernatural/horror genres, and confirmed each is
originally English-language via Wikidata's `P407` field rather than a
translation.

23. **#74** — The Adventures of Tom Sawyer — most-downloaded match found; thin
    Wikidata cast (4 names) so auto-discovery has little to trim
24. **#120** — Treasure Island — see note on row 24 above re: the original
    location-richness drop
25. **#244** — A Study in Scarlet — thin Wikidata cast (6 names), same caveat as #74
26. **#4300** — Ulysses — single-day timeframe, good contrast to this corpus's
    usual multi-year stories
27. **#4217** — A Portrait of the Artist as a Young Man — multi-year Bildungsroman

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
- **Hugo same-city, different era** (#2610 vs. #135): Notre-Dame de Paris (1482)
  and Les Misérables (1815–1832) share Paris geography but centuries apart — good
  test that the pipeline correctly finds NO meetup despite shared location.
- **Ancient-world cluster** (#2145, #2853, #1565): Ben-Hur, Quo Vadis, and The Last
  Days of Pompeii all sit in the 1st century AD across the Roman Mediterranean —
  real meetup candidates if their date ranges and locations overlap.
