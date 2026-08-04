---
summary: Boundary rules for codebases that call models or other probabilistic generators.
read_when:
  - Adding or changing a model call, prompt, provider SDK usage, or generated artifact.
  - Deciding whether automated critique may gate a change.
---

# Generated Content And Model Boundaries

These rules apply to codebases that use AI or other probabilistic generators.
Repositories that call no generator can ignore this document.

## Trust

- Model output is untrusted input. Parse and validate it before use.
- Never let a model waive validation, authorization, or publication rules.
- Human approval stays explicit wherever output is published, safety-sensitive,
  legally meaningful, or difficult to reverse.

## Isolation

- Prompts, provider SDKs, retries, token accounting, and raw responses live
  behind a dedicated boundary.
- Core domain code must not depend on a model provider.
- Parallel model calls are an execution strategy, not a licence for autonomous
  agent orchestration. Prefer a deterministic workflow with explicit stages
  over an agent framework.

## Provenance

- Store accepted outputs and concise provenance, not chain-of-thought or
  self-review prose.
- Do not commit raw prompt transcripts unless the repository explicitly treats
  prompts as versioned product assets.
- Model commentary is not documentation.
- Automated critique is advisory until converted into a deterministic check.

## Artifacts

Every generated artifact carries:

- input identity
- generator or rule version
- creation timestamp
- validation status
- a stable content hash where reproducibility matters
