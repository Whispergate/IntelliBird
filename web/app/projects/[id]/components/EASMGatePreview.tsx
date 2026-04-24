/**
 * EASMGatePreview — Phase 10 read-only scaffold replaced by Phase 11's live form (plan 11-10).
 *
 * Re-exports EASMGateForm as EASMGatePreview for backward compatibility.
 * Any stray imports of EASMGatePreview resolve to the live gate form.
 */
export { EASMGateForm as EASMGatePreview } from "./EASMGateForm";
export type { EASMGateFormProps as EASMGatePreviewProps } from "./EASMGateForm";
