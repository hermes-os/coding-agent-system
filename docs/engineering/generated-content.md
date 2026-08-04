---
summary: Boundaries for codebases that call models or other probabilistic generators.
read_when:
  - Adding or changing code that calls a model.
  - Storing or validating generated artifacts.
---

# Generated Content

Rules for codebases that call models or other probabilistic generators.

- Model output is untrusted input. Parse and validate it before use, and never
  let a model waive validation, authorization, or publication rules.
- Prompts, provider SDKs, retries, token accounting, and raw responses stay
  behind a dedicated boundary. Core domain code does not depend on a provider.
- Store accepted outputs and concise provenance, not reasoning traces or
  self-review prose. Model commentary is not documentation.
- Automated critique is advisory until converted into a deterministic check.
- Human approval stays explicit where output is published, safety-sensitive,
  legally meaningful, or hard to reverse.
- Every generated artifact carries an input identity, a generator or rule
  version, a creation timestamp, validation status, and a stable content hash
  where reproducibility matters.
