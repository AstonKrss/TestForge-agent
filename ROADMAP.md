# Roadmap

TestForge is moving toward a practical AI QA assistant for exploratory, regression, and engineering-grade web testing.

## Now

- Interactive AI CLI
- Multi-agent planning and execution
- Browser automation with Playwright
- Login/search/comment/like style task flows
- Test-plan generation
- Session save/load
- Reports and failure artifacts
- Performance, quality, security, accessibility, and bounded load tests
- Network/API request summaries
- URL-scope site exploration artifacts
- Interactive action IR recording and Playwright Python export

## Next

- Stronger exported tests:
  - richer locator validation
  - better assertions from natural-language goals
  - export successful login/search/comment flows with fewer TODOs

- Non-interactive command runner:

```bash
testforge run --url http://example.com --full --report html
```

- Stronger API assertions:
  - detect login/search/comment/like endpoints
  - assert status codes, schema, timing, and response body
  - generate API-focused report sections

- Better verification:
  - comment appears in list
  - like count changes
  - search results contain keyword
  - login has cookie/localStorage token or protected-page access

- Locator learning:
  - remember successful selectors by domain
  - rank historical locators before fuzzy search
  - self-heal when text or DOM structure changes

- Visual regression:
  - page baselines
  - diff images
  - threshold configuration
  - report integration

- Accessibility:
  - axe-core integration
  - keyboard navigation checks
  - color contrast issues
  - ARIA rule reporting

## Later

- CI/CD integration templates
- Parallel page exploration
- Test data cleanup hooks
- Project-level dashboards
- Team-shared session repositories
- Browser profile reuse with explicit permission
- Plugin system for domain-specific agents

## Principles

- The agent must know when it is uncertain.
- Verification matters more than action count.
- Reports should help a tester debug quickly.
- Full-suite mode must stay safe by default.
- The system should learn from successful runs without leaking secrets.
