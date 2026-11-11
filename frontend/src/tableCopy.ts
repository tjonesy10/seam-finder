export const tableCopy = {
  scopeTitle: "This page",
  scope: "Search, column filters, multi-sort and export apply to this page only.",
  searchLabel: "Search this page",
  searchHelp: "Search includes hidden columns.",
  showing: (filtered: number, loaded: number) => `Showing ${filtered} of ${loaded} loaded rows`,
  exportButton: (count: number) => `Export this page CSV (${count})`,
  exportReady: "Export includes filtered rows on this page.",
  exportLoading: "Export is unavailable while data is loading.",
  exportFailed: "Export is unavailable because the list failed.",
  exportEmpty: "Export is unavailable because no rows match on this page.",
  localEmpty: "No rows match on this page.",
  clearPageFilters: "Clear page filters",
};
