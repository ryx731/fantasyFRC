# BIOCORE kickoff integration contract

The shipped version `biocore-placeholder-v1` is a configurable fantasy template, not official BIOCORE scoring. Real production fields must be mapped after kickoff. All season configuration lives in the league's scoring JSON; core roster/draft/period code does not know game-specific field names.

## Metric contract

Every observation describes **one robot in one played match**, with a globally distinguishable match key (include year, event, level and match number). Never divide alliance scores by three. If an upstream provider only supplies alliance totals, use robot-attributed scouting, omit unsupported weights by setting them to zero, or add an explicitly named estimate metric with a new schema/version and disclose it in the UI. Do not label an estimate as measured robot production.

| Metric | Normalized unit | Standard | Half PPR | Full PPR |
| --- | --- | ---: | ---: | ---: |
| auto | Robot-attributed autonomous production | 1 | 1 | 1 |
| teleop | Robot-attributed teleop production | 1 | 1 | 1 |
| endgame | Robot-attributed endgame contribution | 1 | 1 | 1 |
| cycles | Robot completed scoring cycles | 0 | 0.5 | 1 |
| win | 1 win, 0.5 tie, 0 loss | 5 | 5 | 5 |
| fouls | Positive foul penalty units | -1 | -1 | -1 |

At kickoff, define precisely whether production units are pieces, points, or another robot-level measure. Decide whether giving production and cycle credit together intentionally double rewards that action. Document these definitions for managers in your versioned adapter and update the scoring page's labels if necessary.

Robot-match points = sum(metric × weight). For `average`, each robot's match points are averaged over its played matches within the period, then frozen starter robot scores are added. For `sum`, add all played-match points per starter. A missing robot has zero; a missing required nonzero-weight metric rejects the entire import. All values must be finite and nonnegative. Negative fantasy totals are possible through foul deductions.

## Integration steps

1. Implement a provider adapter outside the fantasy engine. Select completed/played matches for the intended period. Handle qualification/playoff eligibility and provider retries there. Exclude unplayed matches, distinguish replayed matches, and ensure match keys cannot collide across events or seasons.
2. Map released game data to the six normalized metrics. Use `src/tba_client.py` only as a transport where useful; it is not a BIOCORE robot attribution adapter. Store credentials server-side.
3. Before period 1 opens, use commissioner tools (or `POST /api/leagues/{id}/scoring`) to set a new version such as `biocore-2027-v1`, choose aggregation, review all six weights, and activate. Templates can be edited while drafting; they freeze when the first period opens.
4. Set starters. Open the first period through commissioner controls. This snapshots lineups and locks moves.
5. Import JSON through commissioner tools or `POST /api/leagues/{id}/periods/{week}/import` with an authenticated commissioner token. Batch limit: 5,000 observations. Imports are atomic; reimporting a match+robot updates that observation. A robot match already used in another period is rejected.
6. Inspect `GET /api/leagues/{id}/periods/{week}/scores`. Review missing robot data and corrected upstream records. Finalize only when complete. Finalization is immutable through the application. Process waivers between periods, then open the next period.

## Example payload shape (illustrative numbers only)

```json
{
  "rules_version": "biocore-2027-v1",
  "records": [
    {
      "match_key": "2027example_qm1",
      "team_number": 254,
      "metrics": {"auto": 4, "teleop": 12, "endgame": 3, "cycles": 8, "win": 1, "fouls": 0}
    }
  ]
}
```

An adapter can emit this structure without changing league persistence. New metrics require extending `METRICS`, schema/rule validation, the browser labels, and tests under a new rules version. Never silently change a rule version already used in an open season. Automatic provider polling and scheduled period locks are intentionally not configured: the commissioner controls windows and imports until the released game's event schedule and reliable robot attribution are available.
