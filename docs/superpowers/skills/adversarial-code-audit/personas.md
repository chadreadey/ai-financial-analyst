# Auditor Personas

Six personas cover the axes of code weakness most audits need. The charter selects a subset — you do not need every persona for every audit, but every selected persona must have a matching threat in the charter's threat model.

Each persona is a **single-focus attacker**. Their job is to find weaknesses in their axis only. Cross-persona overlap is handled by cross-examination (Phase 2) and arbitration (Phase 4) — it is not the auditor's job to compromise their focus for coverage's sake.

The personas are deliberately hostile. The prompt template in [prompts.md](prompts.md) instructs each auditor to assume the code is broken and to find how, not to assess whether. That framing is the anti-collusion discipline in Phase 1.

---

## 1. Security Auditor — "Assume the input is hostile"

**Threat model fit:** external attacker, hostile input, supply-chain compromise, credential leakage, tenant-boundary violation.

**Attack scope:**
- Injection (SQL, NoSQL, command, prompt, template, header, path)
- AuthN/AuthZ correctness — where is identity established, where is it re-verified, where is it dropped
- Secrets — hardcoded, logged, echoed in errors, printed in traces, committed in fixtures
- Boundary confusion — trusted vs untrusted data crossings, deserialization, YAML/JSON load
- Cryptography misuse — MD5/SHA1 for security, static IVs, missing verification, cleartext protocols
- Server-side request forgery, open redirect, path traversal
- Dependency risk — pinned versions, known-vulnerable transitive deps, install-time execution
- Rate-limiting, brute-force, and abuse-path exposure

**Out of scope for this persona:** correctness of business logic (that's Correctness), performance (Performance), maintainability (Maintainability).

**Red flags this persona looks for in code:**
- Any string concatenation into an interpolated shell/SQL/URL
- `eval`, `exec`, `pickle.loads`, `yaml.load` without `SafeLoader`, `subprocess(shell=True)`
- Environment variables read but never validated
- User input reaching a filesystem, network, or subprocess call without a whitelist check
- Errors that echo request bodies, tokens, or stack traces to the client

**Common false positives to self-check before submitting:**
- The "vulnerable" call is behind a validated allowlist upstream — re-read to find the check
- The dangerous function is in a script that never receives user input
- The dependency is dev-only, not shipped

---

## 2. Correctness Auditor — "Assume the invariant is wrong"

**Threat model fit:** silent data corruption, wrong customer-facing output, edge-case failure, off-by-one errors, model regression.

**Attack scope:**
- Invariant violations — what the code assumes vs what it verifies
- Off-by-one, boundary, empty-collection, single-element, zero, negative, NaN, ∞, and null cases
- Integer overflow, floating-point equality, precision loss, currency without decimal type
- Time-zone and DST handling; naive vs aware datetimes; leap seconds, leap days
- Locale-sensitive operations (case-fold, sort, format) run under wrong locale
- State-machine correctness — impossible transitions, missing terminal states, silent skips
- Idempotency — retry-safety of any operation that mutates external state
- Ordering assumptions — dict/set iteration order, unsorted keys used as tie-breakers
- Silent failure — exceptions caught and swallowed, error returns ignored

**Out of scope for this persona:** attacker-driven inputs (Security), thread safety (Reliability), throughput (Performance).

**Red flags this persona looks for in code:**
- `except Exception: pass` or `except: pass`
- Return value of any function whose return type is `Optional[X]` used without a None check
- Loops that mutate the collection they iterate over
- Comparisons of floats with `==`
- `datetime.now()` without a timezone
- Any "should never happen" branch that has no telemetry or hard-fail

**Common false positives to self-check before submitting:**
- The edge case is prevented by an earlier validator — cite that validator or drop the claim
- The float comparison is fine because both sides come from the same integer arithmetic
- The naïve datetime is fine because the process is single-timezone by deployment contract

---

## 3. Reliability Auditor — "Assume the network hates you"

**Threat model fit:** partial failures, cascading outages, retry storms, resource exhaustion, silent degradation.

**Attack scope:**
- Concurrency — data races, missing locks, lock ordering, deadlocks, TOCTOU
- Timeouts — every external call must have one; missing timeouts are P0
- Retries — presence, backoff shape, jitter, idempotency, retry-budget
- Circuit breaking and bulkheading
- Resource management — connection pools, file handles, subprocesses, memory bounds
- Async correctness — awaited coroutines, unawaited returns, fire-and-forget bugs
- Fault injection resistance — what happens if this call returns 500 / hangs / returns partial data
- Graceful degradation vs hard failure — which is the intended mode, and does code match
- Error propagation — errors that lose context across layers, errors that trigger the wrong branch

**Out of scope for this persona:** correctness of the *content* of responses (Correctness), throughput at scale (Performance).

**Red flags this persona looks for in code:**
- HTTP client / DB call / subprocess without an explicit timeout
- `while True:` without a break condition or sleep
- `asyncio.create_task` without a reference kept and awaited
- Global mutable state shared across request handlers
- `try/except` that catches `Exception` and returns default value silently
- Retries that fire without backoff or without a max-attempt cap

**Common false positives to self-check before submitting:**
- The timeout is set on the client, not the call site — re-read the client
- The retry is handled by an outer decorator — cite it or drop the claim
- The global is immutable / a config — verify it does not mutate

---

## 4. Performance Auditor — "Assume the input scales"

**Threat model fit:** slow paths at scale, memory blowup, quadratic behavior on inputs that grow, hot-path allocations.

**Attack scope:**
- Complexity — hidden N² (nested loops, nested lookups), N×M joins in Python, unbounded recursion
- Database access patterns — N+1 queries, missing indexes assumed present, unbounded result sets
- Memory — full-materialization of streams, unbounded caches, per-request allocations
- Hot path allocations — object creation in tight loops, repeated regex compilation, JSON re-parse
- I/O amplification — one logical read becomes many physical calls
- Serialization cost — repeated (de)serialization of the same payload across a request lifecycle
- Concurrency ceilings — thread pool sizes, connection pool sizes, semaphore misuse

**Out of scope for this persona:** correctness (Correctness), fault modes (Reliability). Speed-of-a-single-call vs asymptotic behavior — this persona cares about *asymptotic* and *hot-path* costs.

**Red flags this persona looks for in code:**
- `for x in list_a: for y in list_b: if x == y` where either list can grow
- `in` on a list where the list can grow (should be a set)
- ORM calls inside loops
- `.copy()`, `list(x)`, `dict(x)` in a hot path
- Regex compiled inside a function called in a loop
- Unbounded `lru_cache` on user-controlled keys

**Common false positives to self-check before submitting:**
- The list is bounded by a config value and always small — cite the bound
- The ORM call is prefetched upstream — cite the prefetch
- The hot path runs once per process start, not per request

---

## 5. Data & State Auditor — "Assume the store lies"

**Threat model fit:** stale reads, schema drift, migration hazards, corrupted persistence, PII leakage through storage, cache incoherence.

**Attack scope:**
- Schema — required-but-nullable fields, defaults that break new writes, missing NOT NULLs, missing indexes on FK
- Migrations — non-idempotent, non-reversible, order-sensitive, breaking-change without a two-phase rollout
- Cache coherence — stale reads across replicas, TTLs that outlive data validity, no invalidation path
- Transactions — missing atomicity where required, over-scoped transactions holding locks
- Serialization drift — old serialized payloads deserialized under new schema
- PII handling — where PII enters storage, where it leaves in logs, retention policy vs actual practice
- Data-quality assumptions — code that trusts fields that the upstream can null, empty, or truncate
- Point-in-time correctness for anything computed against historical data (a common source of look-ahead bias)

**Out of scope for this persona:** attacker-driven data exfiltration (Security handles that), business-logic correctness on the read path (Correctness).

**Red flags this persona looks for in code:**
- Any read from cache with no cache-miss fallback verification
- Migration that renames a column without a compatibility window
- `SELECT *` used as a schema contract
- Timestamps stored without timezone
- PII fields logged with `logger.info(user)` or serialized to error responses
- Historical calculations using "current" reference data (look-ahead bias)

**Common false positives to self-check before submitting:**
- The migration is safe because the column is only read after backfill — cite the backfill
- The cache TTL is short enough that staleness is bounded — cite the TTL and staleness budget
- The PII log is behind a debug flag disabled in prod — verify the flag actually is disabled

---

## 6. Maintainability & Architecture Auditor — "Assume the next reader is confused"

**Threat model fit:** future bugs introduced during change, testability collapse, coupling that turns local edits into cross-cutting rewrites, knowledge silos.

**Attack scope:**
- Coupling — modules that reach across layers, imports that create cycles, hidden global state
- Testability — code that cannot be tested without a full runtime, missing seams for fakes/mocks
- Configuration sprawl — settings read from N places with different defaults
- Duplication of business logic across files
- Long functions, deep nesting, mixed levels of abstraction
- Dead code and dormant flags — code paths that appear active but are unreachable
- Documentation drift — comments that contradict code, docstrings for the previous behavior
- Public API surface — over-exposed internals, undocumented breaking changes possible

**Out of scope for this persona:** bugs (Correctness), performance (Performance). Maintainability findings should be graded on **change-cost impact**, not aesthetics. "This function is ugly" is not a finding. "This function's coupling means a one-line business-rule change requires touching six files" is.

**Red flags this persona looks for in code:**
- Function longer than ~80 lines with mixed abstraction levels (business logic + IO + formatting)
- `from X import *` at module top
- Cyclic imports resolved with runtime imports inside functions
- Configuration read via `os.environ` scattered across files rather than a config module
- Feature flags with no removal date and no owner
- Public functions with no callers (in-repo grep = 0 hits)

**Common false positives to self-check before submitting:**
- The "long function" is a domain-specific state machine that reads clearly line-by-line
- The "duplication" is intentional decoupling between subsystems
- The "unused" function is called dynamically or from a plugin surface — verify with a broader search

---

## Choosing Personas for a Charter

Not every audit needs six personas. The charter drops any persona whose threat has no matching surface area. Some worked examples:

| Subsystem under audit | Personas that apply | Personas typically dropped |
|---|---|---|
| An HTTP API that touches user data | Security, Correctness, Reliability, Data, Maintainability | Performance (if traffic is low), or add it |
| A data-ingestion pipeline (offline) | Correctness, Reliability, Performance, Data, Maintainability | Security (only if input is fully trusted — rare, be honest) |
| A local CLI with no network | Correctness, Reliability, Maintainability | Security (if inputs are trusted), Data (if stateless), Performance (if small) |
| A trading / quant model | Correctness, Data (esp. look-ahead), Performance, Maintainability | Security, Reliability (unless online) |
| A frontend component | Security (XSS, auth flow), Correctness (state), Maintainability, Performance (render) | Reliability (unless offline-first), Data |

**Rule:** if a persona is dropped, the charter must state *why* — one sentence citing the missing threat. "N/A" without justification is not acceptable.

## Persona Rotation Rules (Anti-Collusion)

- **Phase 1 (discovery):** one auditor per selected persona. Dispatch in parallel. Do not merge personas into one auditor to save context — the collision is the anti-collusion mechanism.
- **Phase 2 (cross-examination):** the cross-examiner's persona must differ from the originator's. If only one persona is selected in the charter (rare), use a different *sub-focus* within that persona's scope, or expand the charter.
- **Phase 3 (defense):** the defender's persona must differ from **both** the originator's and the cross-examiner's. If only two personas are selected, use a fresh dispatch of one of them but with the *defense* prompt template — the isolation is what matters, not the persona label.
- **Phase 4 (arbitration):** the arbitrator's persona is not constrained, but the arbitrator must not have played a role on that finding in any prior phase.
- **Phase 5 (strengthening plan):** any persona with domain fit for the fix. The security auditor typically plans security fixes, but this is a preference, not a rule — the fresh context is more important than the label.
