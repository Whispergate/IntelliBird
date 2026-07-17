"""TIBER report generation service layer — TIBER-01..04.

Sub-modules:
  auto_populate  — 4 section auto-populate functions (Threat Landscape, Actor Profiles,
                   Scenarios Longlist, Actionable Intelligence). All routed through
                   events_query.build_scope_predicate + graph_traversal (H-4 chokepoint).
  validators     — completeness_check + scenario_gate_check (section + scenario gates).
  cbest          — relabel_cif_to_cbs (CIF → Critical Business Service flip for CBEST mode).
  exporters/     — markdown, pdf, stix exporters.
"""
