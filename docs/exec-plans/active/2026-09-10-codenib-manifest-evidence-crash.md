# Bug report: symbol-graph build crashes on repos with ≥2 internal manifest dependencies

- **Upstream repo:** `../CodeNib` at `ed6c04c0` (installed via
  `uv tool install "codenib[graph,mcp] @ file:///home/pursottam/mine/projects/CodeNib"`)
- **Trigger repo:** `ai-saas-starter-kit` at `f95c9fc`
  ("feat(services): extract shared key validation + minimal worker service")
- **Severity:** hard failure — `symbol_graph` view reports `failed`, manifest keeps the
  last indexed identity, serving falls back to the stale graph (`verified:false` reads).
- **Date:** 2026-09-10

## Repro (deterministic, 3/3 runs)

```bash
codenib index /home/pursottam/mine/projects/ai-saas-starter-kit --preset graph --rebuild
# Views:
#   bm25           fresh
#   symbol_graph   failed (∼18s)
# Failed to build symbol_graph: Value after * must be an iterable, not NoneType
```

Minimal trigger: any repo whose workspace has **two or more resolved internal
manifest dependencies** (e.g. two pyprojects both depending on one shared package).
One manifest edge builds fine; the second detonates enrichment.

## Observed vs expected

- Observed: `Failed to build symbol_graph: Value after * must be an iterable, not NoneType`.
  The failure occurs *after* "Built combined graph" (decoder output is fine).
- Expected: enrichment records one `depends_on_manifest` edge per resolved internal
  dependency and the view reports `fresh`.

## Root cause (verified by in-process repro with traceback)

`codenib/graph/code_graph.py:598`, inside `CodeGraph.add_architecture_edge`:

```python
edge_id = self._add_edge(source_name, target_name, edge_type)
if edge_type == EDGE_TYPE_MANIFEST_DEPENDENCY and normalized_evidence:
    existing = self.graph.es[edge_id].attributes().get("manifest_evidence", ())
    merged = _normalize_manifest_evidence([*existing, *normalized_evidence])  # 💥 line 598
```

igraph auto-fills every newly created edge with `None` for **all registered edge
attributes**. Sequence of events:

1. The first manifest edge (`project://apps/web → project://packages/shared`) is
   created. At that point `manifest_evidence` is not yet a registered edge attribute,
   so `.get("manifest_evidence", ())` returns `()`. The merge succeeds and the
   assignment registers `manifest_evidence` graph-wide.
2. The second manifest edge (`project://services/api → project://services/shared`)
   is created via `_add_edge`, which only sets `type` — igraph fills
   `manifest_evidence=None`. Now the key is *present but None*, so the `()`
   default does not apply and `[*None]` raises `TypeError`.

Instrumented proof (spy on `add_architecture_edge` against the on-disk `graph.pkl`):

```text
edge attrs at load: ['type', 'anchor_file', 'anchor_line']
FAILING EDGE: project://services/api -> project://services/shared depends_on_manifest
edge attrs now: ['type', 'anchor_file', 'anchor_line', 'manifest_evidence']
edge value: None
CONFIRMED: Value after * must be an iterable, not NoneType
```

Call chain: `index_builders.py` symbol-graph builder → `pre_save_hook` →
`enrich_graph_with_workspace` (`codenib/graph/workspace_enrichment.py:754`,
the manifest-edge loop) → `add_architecture_edge` → line 598.

## Why it stayed latent

The fixture repo previously had exactly **one** resolved internal manifest edge
(`apps/web → packages/shared`), so the register-then-read-None sequence never
occurred. Any monorepo with a shared library consumed by 2+ projects hits it.

## Proposed fix (untested, one line at the source)

```python
existing = self.graph.es[edge_id].attributes().get("manifest_evidence") or ()
```

Rationale: fix at the read site, not the symptom — both "absent" and "present-but-None"
mean "no prior evidence". Suggested regression test: build/merge two manifest edges
onto one graph in a unit test (mirror of `test_codegraph_onboarding.py` style), plus
an enrichment test over a fixture with two sibling consumers of one shared package.

Also consider auditing sibling `.get(<attr>, <default>)` reads on igraph edge/vertex
attributes for the same present-but-None trap.

## Workarounds considered

None viable without gutting the feature: any 2+ internal manifest edges crash
deterministically. Downgrading to a single consumer, or hand-editing the manifest
graph, would falsify the very topology under test.

## Impact on the trigger repo (our side, all committed, no action needed)

- `ai-saas-starter-kit@f95c9fc` is complete and green on its own gates:
  `test:api` 238 passed, `test:shared` 7 passed, `test:worker` 3 passed,
  `lint` clean in all three packages, `check:structure` 6 passed.
- `scan_workspace` already proves the intended topology: 6 projects (was 4),
  `services/api → services/shared` and `services/worker → services/shared`
  edges with `name` resolution, and `services/api` now carries its display name.
- Blocked pending upstream fix: index rebuild with enrichment, fresh `graph.pkl`
  project nodes, `explore_context verified:true` on the new files, and the
  post-rebuild `dependency_subgraph` blast-radius check on
  `services/shared/src/shared/keys.py:has_path_traversal`
  (pre-rebuild query correctly traces the old location — stale index, expected).
- Pre-existing edge in the same area: my earlier verification driver double-added
  architecture vertices the pipeline now owns and tripped the schema-7
  `architecture_digest` guard — that was a driver artifact, not a product bug.
  Do not confuse the two.
