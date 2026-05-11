```yaml
issue_id: 101
title: "add example fetcher"
classification: auto-fixable
scope: small
goal: "implement a tiny new fetcher"
acceptance_criteria:
  - "new fetcher returns Article list"
  - "pytest passes"
constraints:
  - "no new external API"
impacted_areas:
  - fetchers/
target_tests:
  - tests/fetchers/test_example.py
stop_conditions:
  - "YouTube search.list newly required"
out_of_scope:
  - unrelated refactor
```
