type PipelineRootIdentity = {
  kind: "import_job" | "update_request";
  id: string;
};

/** UUID가 같아도 root kind가 다른 canonical 실행은 별도 table 행이다. */
export function canonicalPipelineRootRowId(row: PipelineRootIdentity): string {
  return `${row.kind}:${row.id}`;
}
