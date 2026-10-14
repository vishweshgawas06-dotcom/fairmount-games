# FairMount Roulette — Canonical Legal-Position Catalogue (Review Draft)

**Status:** Draft for owner review — not yet accepted as the implementation catalogue  
**Scope:** Standard single-zero European roulette table only  
**Purpose:** Define legal number combinations for inside bets before any betting-engine code is written.

## 1. Canonical table geometry

The numbered grid has 12 rows of three numbers:

- Row 1: 1, 2, 3
- Row 2: 4, 5, 6
- Row 3: 7, 8, 9
- Row 4: 10, 11, 12
- Row 5: 13, 14, 15
- Row 6: 16, 17, 18
- Row 7: 19, 20, 21
- Row 8: 22, 23, 24
- Row 9: 25, 26, 27
- Row 10: 28, 29, 30
- Row 11: 31, 32, 33
- Row 12: 34, 35, 36

The green zero pocket sits above the numbered grid. Bet selections must be validated against the rules below, not against client-provided labels or coordinates.

## 2. Legal inside selections

### Straight-up
- Every integer pocket from 0 through 36, inclusive.

### Split
- **Horizontal splits:** adjacent numbers within the same three-number row: (1,2), (2,3), (4,5), (5,6), continuing through (34,35), (35,36).
- **Vertical splits:** same column in adjacent numbered rows: (1,4), (2,5), (3,6), continuing through (31,34), (32,35), (33,36).
- **Zero splits:** (0,1), (0,2), and (0,3).
- No diagonal splits.

### Street
- Each complete numbered row: (1,2,3), (4,5,6), continuing through (34,35,36).
- **Zero-adjacent streets:** (0,1,2) and (0,2,3).
- No other three-number combinations.

### Corner
- Every 2×2 block spanning two adjacent numbered rows and two adjacent columns. For each row pair (1–2, 2–3, 3–4, continuing through 11–12), and each column pair (left+middle, middle+right), include the four-number set formed by those positions.
- Examples: (1,2,4,5), (2,3,5,6), (4,5,7,8).
- No diagonal or zero-adjacent generic corners. The (0,1,2,3) set is represented by the distinct First Four bet type below.

### Six line
- Every pair of adjacent numbered streets: (1,2,3,4,5,6), (4,5,6,7,8,9), continuing in three-number increments through (31,32,33,34,35,36).
- No six-line containing zero.

### First Four
- Exactly the set (0,1,2,3), represented as its own bet type, not as a generic corner.

## 3. Legal outside selections

Outside selections use named canonical values rather than arbitrary number arrays:

- Dozen 1: 1–12; Dozen 2: 13–24; Dozen 3: 25–36.
- Column 1: 1,4,7,10,13,16,19,22,25,28,31,34.
- Column 2: 2,5,8,11,14,17,20,23,26,29,32,35.
- Column 3: 3,6,9,12,15,18,21,24,27,30,33,36.
- Red and Black: the standard European roulette color mapping, stored as a fixed audited set.
- Odd and Even: numbers 1–36 with the stated parity; zero is neither.
- Low: 1–18; High: 19–36.
- Zero is excluded from all outside selections.

The red/black mapping must be stored as a fixed canonical list and covered by tests; it must not be inferred from the number's position or client state.

## 4. Validation and normalization rules

- Represent a selection using a bet-type enum plus canonical selection identifier or sorted number set.
- Reject a selection if its type/number set is not in the catalogue.
- Canonicalize number sets by sorting ascending and reject duplicates within one selection.
- Do not treat reversed number order as a different selection; for example, split (17,20) and (20,17) refer to the same canonical selection.
- Keep duplicate accepted bet records separate for history/accounting, while aggregate caps use the canonical selection identifier.
- Apply the approved 2,000-coin per-number exposure cap across straight-up and split bets, and the 2,000-coin per-player/per-round cap for each exact outside or multi-number selection as specified in the approved payout/settlement specification.
- Validate all selections, applicable caps, balance, chip/minimum rules, and betting cutoff on the server in one concurrency-safe operation.
- The animation uses the persisted server outcome and has no authority over selection validity or settlement.

## 5. Catalogue counts to verify in automated tests

Expected counts from the rules above:

- Straight-up: 37
- Horizontal splits: 24
- Vertical splits: 33
- Zero splits: 3
- Total splits: 60
- Numbered streets: 12
- Zero-adjacent streets: 2
- Total streets: 14
- Generic corners: 44 (11 adjacent row-pairs × 2 adjacent column-pairs × 2? See review note below)
- Six lines: 11
- First Four: 1

**Count review note:** The generic-corner count must be verified against the actual table geometry before locking. There are 11 adjacent row-pairs and 2 adjacent column-pairs per row-pair, yielding 22 generic 2×2 corners under the geometry defined above. The provisional value “44” is not authoritative and is explicitly superseded by this derivation; expected generic-corner count is **22**.

## 6. Owner review checklist

Please review and confirm or correct:

1. The zero-adjacent catalogue: splits (0,1), (0,2), (0,3); streets (0,1,2) and (0,2,3); First Four (0,1,2,3).
2. Generic corners are limited to the 22 2×2 blocks in the numbered grid, with no separate generic zero corner.
3. Six lines are adjacent pairs of numbered streets only.
4. The exact standard red/black mapping will be encoded as a fixed audited list.
5. The catalogue and counts must be tested before the betting engine is implemented.

**No betting-engine implementation is authorized by this draft.**
