# Retrieval experiment tables (auto-generated)

Source: `results/raw/retrieval_grid_per_question.csv` (1728 rows). 30 answerable + 6 unanswerable questions per config.

Re-rank cost measured at 68 ms per (question, chunk) pair on a 2-vCPU sandbox, x20 candidates = 1359 ms per question.

Tokens are estimated as characters / 4 of the retrieved chunks (context only, not the prompt template).

## T1. Full grid (hits out of 30 answerable)

| Config | hit@3 | hit@5 | hit@8 | MRR | tokens@5 | retrieval ms/question |
|---|---|---|---|---|---|---|
| raw / section / hybrid | 21 | 26 | 26 | 0.62 | 2074 | 46 |
| clean / section / hybrid | 20 | 25 | 26 | 0.64 | 2076 | 47 |
| clean / w200 / bm25 +rerank | 19 | 24 | 27 | 0.59 | 1515 | 1361 |
| raw / w200 / bm25 +rerank | 19 | 24 | 27 | 0.58 | 1529 | 1361 |
| raw / section / bm25 +rerank | 21 | 24 | 26 | 0.56 | 2116 | 1361 |
| clean / w400 / hybrid +rerank | 21 | 23 | 26 | 0.60 | 2711 | 1412 |
| raw / w200 / hybrid +rerank | 20 | 23 | 24 | 0.59 | 1493 | 1413 |
| raw / w400 / hybrid +rerank | 21 | 23 | 25 | 0.59 | 2743 | 1410 |
| raw / w200 / hybrid | 21 | 23 | 24 | 0.58 | 1523 | 52 |
| clean / w200 / hybrid +rerank | 20 | 23 | 25 | 0.57 | 1486 | 1413 |
| clean / section / bm25 +rerank | 20 | 23 | 27 | 0.57 | 2093 | 1360 |
| clean / w400 / bm25 +rerank | 20 | 23 | 25 | 0.56 | 2802 | 1360 |
| clean / section / hybrid +rerank | 20 | 23 | 26 | 0.55 | 2108 | 1410 |
| raw / section / hybrid +rerank | 20 | 23 | 25 | 0.54 | 2110 | 1406 |
| raw / w100 / hybrid +rerank | 17 | 23 | 26 | 0.54 | 772 | 1417 |
| raw / w400 / hybrid | 20 | 23 | 26 | 0.54 | 2722 | 48 |
| raw / section / dense +rerank | 20 | 23 | 24 | 0.53 | 2092 | 1410 |
| clean / w200 / dense +rerank | 19 | 23 | 23 | 0.53 | 1463 | 1413 |
| raw / w400 / bm25 +rerank | 19 | 23 | 25 | 0.52 | 2832 | 1360 |
| raw / section / bm25 | 19 | 22 | 23 | 0.59 | 2049 | 1 |
| clean / section / bm25 | 19 | 22 | 24 | 0.58 | 2052 | 0 |
| raw / w200 / dense | 18 | 22 | 23 | 0.57 | 1417 | 45 |
| clean / w200 / hybrid | 18 | 22 | 24 | 0.55 | 1503 | 50 |
| clean / w400 / dense +rerank | 21 | 22 | 22 | 0.54 | 2712 | 1411 |
| raw / w400 / dense +rerank | 20 | 22 | 23 | 0.54 | 2760 | 1413 |
| raw / w200 / dense +rerank | 20 | 22 | 23 | 0.53 | 1470 | 1415 |
| raw / w100 / dense +rerank | 18 | 22 | 22 | 0.52 | 774 | 1413 |
| clean / section / dense | 18 | 22 | 24 | 0.50 | 2016 | 48 |
| clean / section / dense +rerank | 18 | 22 | 24 | 0.50 | 2154 | 1410 |
| clean / w200 / dense | 20 | 21 | 22 | 0.57 | 1412 | 49 |
| clean / w400 / hybrid | 20 | 21 | 25 | 0.53 | 2746 | 50 |
| clean / w100 / hybrid +rerank | 15 | 21 | 25 | 0.52 | 774 | 1412 |
| raw / w100 / bm25 +rerank | 18 | 21 | 24 | 0.50 | 776 | 1362 |
| raw / w400 / bm25 | 16 | 21 | 24 | 0.49 | 2696 | 1 |
| raw / w200 / bm25 | 13 | 21 | 25 | 0.48 | 1529 | 1 |
| clean / w100 / dense +rerank | 14 | 21 | 22 | 0.47 | 776 | 1413 |
| clean / w100 / bm25 +rerank | 17 | 20 | 22 | 0.51 | 775 | 1361 |
| raw / section / dense | 18 | 20 | 23 | 0.51 | 2047 | 53 |
| clean / w200 / bm25 | 15 | 20 | 24 | 0.49 | 1512 | 1 |
| clean / w400 / bm25 | 16 | 20 | 24 | 0.48 | 2686 | 1 |
| raw / w400 / dense | 17 | 19 | 21 | 0.50 | 2427 | 48 |
| raw / w100 / hybrid | 18 | 19 | 23 | 0.49 | 780 | 56 |
| clean / w400 / dense | 16 | 19 | 21 | 0.48 | 2488 | 41 |
| raw / w100 / dense | 15 | 19 | 21 | 0.46 | 756 | 48 |
| clean / w100 / dense | 16 | 18 | 20 | 0.48 | 760 | 46 |
| clean / w100 / hybrid | 13 | 18 | 20 | 0.40 | 777 | 48 |
| raw / w100 / bm25 | 13 | 14 | 17 | 0.38 | 772 | 1 |
| clean / w100 / bm25 | 11 | 13 | 16 | 0.37 | 763 | 1 |

## T2. One change at a time from the baseline (raw / w200 / bm25, no rerank)

| Change | Config | hit@3 | hit@5 | hit@8 | MRR | tokens@5 | ms |
|---|---|---|---|---|---|---|---|
| baseline | raw / w200 / bm25 | 13 | 21 | 25 | 0.48 | 1529 | 1 |
| strip headers | clean / w200 / bm25 | 15 | 20 | 24 | 0.49 | 1512 | 1 |
| chunk 100 | raw / w100 / bm25 | 13 | 14 | 17 | 0.38 | 772 | 1 |
| chunk 400 | raw / w400 / bm25 | 16 | 21 | 24 | 0.49 | 2696 | 1 |
| section chunks | raw / section / bm25 | 19 | 22 | 23 | 0.59 | 2049 | 1 |
| embeddings | raw / w200 / dense | 18 | 22 | 23 | 0.57 | 1417 | 45 |
| hybrid | raw / w200 / hybrid | 21 | 23 | 24 | 0.58 | 1523 | 52 |
| rerank | raw / w200 / bm25 +rerank | 19 | 24 | 27 | 0.58 | 1529 | 1361 |

## T3. hit@5 by question type (clean text unless noted)

| Config | exact (n=15) | paraphrase (n=8) | header_trap (n=4) | transcript (n=1) | cross_paper (n=2) |
|---|---|---|---|---|---|
| raw / w200 / bm25 | 13 | 3 | 2 | 1 | 2 |
| clean / w200 / bm25 | 13 | 3 | 1 | 1 | 2 |
| clean / w200 / dense | 11 | 6 | 2 | 1 | 1 |
| clean / w200 / hybrid | 12 | 5 | 3 | 1 | 1 |
| clean / w200 / bm25 +rerank | 12 | 6 | 3 | 1 | 2 |
| clean / w200 / hybrid +rerank | 12 | 6 | 3 | 1 | 1 |
| clean / section / hybrid +rerank | 11 | 7 | 3 | 1 | 1 |

## T4. Paired comparison at hit@5: questions gained / lost vs. a reference

| Reference -> Variant | gained | lost | net | which |
|---|---|---|---|---|
| raw / w200 / bm25 -> clean / w200 / bm25 | 0 | 1 | -1 | +- / -M4 |
| clean / w200 / bm25 -> clean / w200 / dense | 7 | 6 | +1 | +A8,A9,M1,M3,M8,M9,D4 / -M5,M6,M10,D2,D3,X1 |
| clean / w200 / bm25 -> clean / w200 / hybrid | 6 | 4 | +2 | +A8,A9,M1,M4,M8,M9 / -M5,M6,D3,X1 |
| clean / w200 / hybrid -> clean / w200 / hybrid +rerank | 4 | 3 | +1 | +M3,M5,D3,D5 / -M4,M10,D2 |
| clean / w200 / bm25 -> clean / w200 / bm25 +rerank | 7 | 3 | +4 | +A8,A9,M1,M3,M8,M9,D5 / -M6,M10,D2 |
| clean / w200 / hybrid +rerank -> clean / section / hybrid +rerank | 3 | 3 | +0 | +M6,D2,D4 / -A9,M2,D3 |
| clean / w200 / hybrid +rerank -> clean / w100 / hybrid +rerank | 3 | 5 | -2 | +M10,D4,X1 / -A5,M2,M5,D1,D5 |
| clean / w200 / hybrid +rerank -> clean / w400 / hybrid +rerank | 1 | 1 | +0 | +M4 / -D3 |

## T5. Can the top-1 retrieval score flag unanswerable questions? (clean / w200)

AUC = probability a random answerable question scores higher than a random unanswerable one (0.5 = useless, 1.0 = perfect). 'Best threshold' = accuracy of the best single cut over all 36.

| Retriever | AUC | best threshold accuracy | lowest answerable score | highest unanswerable score (which) |
|---|---|---|---|---|
| bm25 | 0.64 | 83% | 8.939 | 30.774 (U1) |
| bm25 +rerank | 0.72 | 89% | -2.557 | 4.886 (U1) |
| dense | 0.79 | 94% | 0.718 | 0.831 (U6) |
| dense +rerank | 0.72 | 89% | -2.557 | 4.886 (U1) |
| hybrid | 0.70 | 89% | 0.029 | 0.033 (U3) |
| hybrid +rerank | 0.73 | 89% | -2.557 | 4.886 (U1) |

## T6. k tradeoff (clean text)

| Config | hit@3 / tokens | hit@5 / tokens | hit@8 / tokens |
|---|---|---|---|
| clean / w200 / bm25 | 15 / 910 | 20 / 1512 | 24 / 2402 |
| clean / w200 / hybrid | 18 / 914 | 22 / 1503 | 24 / 2426 |
| clean / w200 / hybrid +rerank | 20 / 876 | 23 / 1486 | 25 / 2399 |
| clean / w100 / hybrid +rerank | 15 / 462 | 21 / 774 | 25 / 1242 |
| clean / w400 / hybrid | 20 / 1616 | 21 / 2746 | 25 / 4311 |
| clean / section / hybrid +rerank | 20 / 1223 | 23 / 2108 | 26 / 3525 |

## T7. Per-question hit@5 across all 48 configs

| Question | type | configs that hit@5 (of 48) |
|---|---|---|
| A6 | paraphrase | 0 |
| D5 | paraphrase | 9 |
| X1 | cross_paper | 14 |
| D2 | exact | 18 |
| D3 | exact | 20 |
| D4 | paraphrase | 21 |
| M6 | exact | 22 |
| M10 | exact | 22 |
| M4 | header_trap | 24 |
| A9 | exact | 34 |
| M3 | exact | 34 |
| D1 | exact | 34 |
| M9 | paraphrase | 35 |
| D6 | exact | 37 |
| A8 | paraphrase | 38 |
| A5 | paraphrase | 39 |
| M2 | exact | 40 |
| M5 | header_trap | 40 |
| M8 | header_trap | 41 |
| M1 | header_trap | 42 |
| M7 | paraphrase | 44 |
| X2 | cross_paper | 45 |
| A4 | exact | 46 |
| A7 | exact | 46 |
| A10 | paraphrase | 46 |
| A1 | exact | 48 |
| A2 | exact | 48 |
| A3 | exact | 48 |
| M11 | transcript | 48 |
| D7 | exact | 48 |
