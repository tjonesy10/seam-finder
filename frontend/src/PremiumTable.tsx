import { useEffect, useRef, useState } from "react";
import type { ColumnFiltersState, OnChangeFn, SortingState } from "@tanstack/react-table";
import type { LegacyColumnDef } from "@tanstack/react-table/legacy";
import type { Row } from "./api";
import { clampWidth, columnMeta, initialWidth, isNumericKind, resourceColumns, type ColumnMeta } from "./columns";
import { buildCsv, csvFilename, downloadCsv } from "./csv";
import { DataTable, type ColumnCellMeta } from "./DataTable";
import { POINTS_LEGEND, formatValue, pointsBackground, pointsExtent } from "./format";
import {
  addSort,
  cycleHeaderSort,
  moveSort,
  multiOptions,
  pageExport,
  pageManualRows,
  parseDecimalInput,
  removeSort,
  toggleSortDirection,
} from "./refine";
import type { ColumnFilter, MultiFilter, PageUi, RangeFilter, TableState } from "./pageState";
import { emptyUi } from "./pageState";
import type { Resource } from "./resources";
import { tableCopy } from "./tableCopy";
import styles from "./premium.module.css";
import pageStyles from "./pages.module.css";

type HistoryMode = "push" | "replace";
type Phase = "loading" | "error" | "ready";

function patchUi(state: TableState, ui: Partial<PageUi>): TableState {
  return { ...state, ui: { ...state.ui, ...ui } };
}

export function PremiumTable({
  resource,
  rows,
  successfulRows,
  state,
  phase,
  fresh,
  onState,
}: {
  resource: Resource;
  rows: Row[];
  successfulRows: Row[] | null;
  state: TableState;
  phase: Phase;
  fresh: boolean;
  onState: (next: TableState, history: HistoryMode) => void;
}) {
  const stateRef = useRef(state);
  const onStateRef = useRef(onState);
  stateRef.current = state;
  onStateRef.current = onState;
  const [liveWidths, setLiveWidths] = useState<Record<string, number>>({});
  const [openFilter, setOpenFilter] = useState<string | null>(null);
  const [sortOpen, setSortOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [full, setFull] = useState<{ label: string; value: string } | null>(null);
  const filterButton = useRef<HTMLButtonElement | null>(null);
  const sortButton = useRef<HTMLButtonElement | null>(null);
  const columnsButton = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const filtered = phase === "ready" ? pageManualRows(rows, state.ui, resource) : [];
  const visible = resourceColumns(resource).filter((meta) => !state.ui.hidden.includes(meta.key));
  const hasPoints = resource.columns.includes("fantasy_points") || resource.columns.includes("fantasy_points_ppr");
  const extents = new Map(
    ["fantasy_points", "fantasy_points_ppr"].map((key) => [key, pointsExtent(filtered.map((row) => row[key]))]),
  );

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !full) return;
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
    else dialog.setAttribute("open", "");
  }, [full]);

  function commit(next: TableState, history: HistoryMode) {
    onStateRef.current(next, history);
  }

  function commitWidth(key: string, width: number, history: HistoryMode) {
    const current = stateRef.current;
    const widths = { ...current.ui.widths };
    if (width === initialWidth(key)) delete widths[key];
    else widths[key] = width;
    commit(patchUi(current, { widths }), history);
  }

  function closeFull() {
    const dialog = dialogRef.current;
    if (dialog && typeof dialog.close === "function" && dialog.open) dialog.close();
    setFull(null);
    openerRef.current?.focus();
  }

  const columns: LegacyColumnDef<Row>[] = visible.map((meta) => {
    const width = liveWidths[meta.key] ?? state.ui.widths[meta.key] ?? meta.width;
    const priority = state.ui.sort.findIndex((entry) => entry.id === meta.key);
    const direction = priority >= 0 && state.ui.sort[priority].desc ? "descending" : "ascending";
    const extent = extents.get(meta.key) ?? { min: null, max: null };
    const cellMeta: ColumnCellMeta = {
      width,
      numeric: isNumericKind(meta.kind),
      points: meta.kind === "points",
      ariaSort: priority === 0 ? direction : "none",
      pointsBgFor: meta.kind === "points" ? (value) => pointsBackground(value, extent.min, extent.max) : undefined,
    };
    return {
      id: meta.key,
      accessorKey: meta.key,
      header: () => (
        <div className={styles.header}>
          <button
            type="button"
            aria-label={
              priority >= 0
                ? `Sort by ${meta.label} ${priority + 1}${direction === "descending" ? "↓" : "↑"}, priority ${priority + 1} ${direction}`
                : `Sort by ${meta.label}`
            }
            onClick={(event) => {
              const current = stateRef.current;
              commit(patchUi(current, { sort: cycleHeaderSort(current.ui.sort, meta.key, event.shiftKey) }), "push");
            }}
          >
            <span>{meta.label}</span>
            {priority >= 0 ? <span>{` ${priority + 1}${direction === "descending" ? "↓" : "↑"}`}</span> : null}
          </button>
          {meta.kind === "points" ? <span className={styles.srOnly}>{POINTS_LEGEND}</span> : null}
          <button
            type="button"
            ref={openFilter === meta.key ? filterButton : undefined}
            aria-expanded={openFilter === meta.key}
            aria-controls={openFilter === meta.key ? `filter-${meta.key}` : undefined}
            aria-label={`Column filter for ${meta.label}`}
            onClick={(event) => {
              filterButton.current = event.currentTarget;
              setOpenFilter((current) => (current === meta.key ? null : meta.key));
            }}
          >
            Column filter
          </button>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-valuemin={96}
            aria-valuemax={480}
            aria-valuenow={width}
            aria-label={`Resize ${meta.label}`}
            tabIndex={0}
            className={styles.resize}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight") {
                event.preventDefault();
                commitWidth(meta.key, clampWidth(width + 16), "push");
              } else if (event.key === "ArrowLeft") {
                event.preventDefault();
                commitWidth(meta.key, clampWidth(width - 16), "push");
              } else if (event.key === "Home") {
                event.preventDefault();
                commitWidth(meta.key, initialWidth(meta.key), "push");
              }
            }}
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              event.preventDefault();
              event.stopPropagation();
              const startX = event.clientX;
              const startWidth = width;
              const move = (pointer: PointerEvent) => {
                setLiveWidths((current) => ({ ...current, [meta.key]: clampWidth(startWidth + pointer.clientX - startX) }));
              };
              const up = (pointer: PointerEvent) => {
                window.removeEventListener("pointermove", move);
                window.removeEventListener("pointerup", up);
                setLiveWidths((current) => {
                  const next = { ...current };
                  delete next[meta.key];
                  return next;
                });
                commitWidth(meta.key, clampWidth(startWidth + pointer.clientX - startX), "push");
              };
              window.addEventListener("pointermove", move);
              window.addEventListener("pointerup", up);
            }}
          />
        </div>
      ),
      cell: (info) => {
        const value = info.getValue();
        const display = formatValue(value, meta.kind);
        const raw = display.missing ? "" : String(value ?? "");
        const shown = display.missing ? (
          <span aria-label="Missing">{display.text}</span>
        ) : (
          <span className={styles.cellText} aria-describedby={meta.kind === "points" ? "points-legend" : undefined}>
            {display.text}
          </span>
        );
        return (
          <div className={styles.cell}>
            {shown}
            {raw.length > 32 ? (
              <button
                type="button"
                className={styles.full}
                aria-label={`Show full ${meta.label}`}
                onClick={(event) => {
                  openerRef.current = event.currentTarget;
                  setFull({ label: meta.label, value: raw });
                }}
              >
                Full value
              </button>
            ) : null}
          </div>
        );
      },
      meta: cellMeta,
    };
  });

  const sorting: SortingState = [];
  const columnFilters: ColumnFiltersState = [];
  const onSortingChange: OnChangeFn<SortingState> = () => undefined;
  const onColumnFiltersChange: OnChangeFn<ColumnFiltersState> = () => undefined;
  const localEmpty = phase === "ready" && rows.length > 0 && filtered.length === 0;
  const exportable = phase === "ready" && fresh && filtered.length > 0;
  let exportReason = tableCopy.exportReady;
  if (phase === "error") exportReason = tableCopy.exportFailed;
  else if (!fresh || phase === "loading") exportReason = tableCopy.exportLoading;
  else if (filtered.length === 0) exportReason = tableCopy.exportEmpty;

  return (
    <div className={styles.tools}>
      <h2>{tableCopy.scopeTitle}</h2>
      <p className={styles.scope}>{tableCopy.scope}</p>
      <SearchBox value={state.ui.search} onCommit={(value, history) => commit(patchUi(stateRef.current, { search: value }), history)} />
      <p className={styles.help}>{tableCopy.searchHelp}</p>
      <div className={styles.actions}>
        <button
          type="button"
          className={pageStyles.button}
          ref={sortButton}
          aria-expanded={sortOpen}
          aria-controls="sort-panel"
          onClick={() => setSortOpen((open) => !open)}
        >
          Sort
        </button>
        <button
          type="button"
          className={`${pageStyles.button} ${pageStyles.buttonSecondary}`}
          ref={columnsButton}
          aria-expanded={columnsOpen}
          aria-controls="column-chooser"
          onClick={() => setColumnsOpen((open) => !open)}
        >
          Columns
        </button>
        <button
          type="button"
          className={`${pageStyles.button} ${pageStyles.buttonSecondary}`}
          onClick={() => commit(patchUi(stateRef.current, emptyUi()), "push")}
        >
          Reset this page
        </button>
        <button
          type="button"
          className={pageStyles.button}
          disabled={!exportable}
          aria-describedby="export-reason"
          onClick={() => {
            if (!exportable || !successfulRows) return;
            const snapshot = pageExport(
              successfulRows,
              stateRef.current.ui,
              resource,
              visible.map((meta) => meta.key),
            );
            downloadCsv(csvFilename(resource.pagePath.slice(1), new Date()), buildCsv(snapshot.columns, snapshot.rows));
          }}
        >
          {tableCopy.exportButton(filtered.length)}
        </button>
        <a href="#attribution">nflverse attribution</a>
      </div>
      <p id="export-reason" className={styles.help}>
        {exportable ? "Export includes filtered rows on this page." : exportReason}
      </p>
      {phase === "ready" ? <p>{tableCopy.showing(filtered.length, rows.length)}</p> : null}
      <p>
        {state.ui.sort.length === 0
          ? "Page sort: server order"
          : `Page sort: ${state.ui.sort
              .map((entry, index) => `${index + 1}. ${columnMeta(entry.id).label} ${entry.desc ? "descending" : "ascending"}`)
              .join(", ")}`}
      </p>
      {openFilter ? (
        <div id={`filter-${openFilter}`} role="region" aria-label={`Filter ${columnMeta(openFilter).label}`}>
          <FilterPanel
            meta={columnMeta(openFilter)}
            rows={rows}
            filter={state.ui.filters[openFilter]}
            onClose={() => {
              setOpenFilter(null);
              filterButton.current?.focus();
            }}
            onApply={(filter, history) => {
              const current = stateRef.current;
              const filters = { ...current.ui.filters };
              if (!filter) delete filters[openFilter];
              else filters[openFilter] = filter;
              commit(patchUi(current, { filters }), history);
            }}
          />
        </div>
      ) : null}
      <FilterChips
        resource={resource}
        ui={state.ui}
        onRemove={(key, value) => {
          const current = stateRef.current;
          if (key === "search") {
            commit(patchUi(current, { search: "" }), "push");
            return;
          }
          const filters = { ...current.ui.filters };
          const existing = filters[key];
          if (!existing || existing.kind !== "multi" || value === undefined) delete filters[key];
          else {
            const values = value === "missing" ? existing.values : existing.values.filter((item) => item !== value);
            const missing = value === "missing" ? false : existing.missing;
            if (values.length === 0 && !missing) delete filters[key];
            else filters[key] = { kind: "multi", values, missing };
          }
          commit(patchUi(current, { filters }), "push");
        }}
      />
      {sortOpen ? (
        <SortPanel
          resource={resource}
          sort={state.ui.sort}
          onClose={() => {
            setSortOpen(false);
            sortButton.current?.focus();
          }}
          onChange={(sort) => commit(patchUi(stateRef.current, { sort }), "push")}
        />
      ) : null}
      {columnsOpen ? (
        <ColumnChooser
          resource={resource}
          hidden={state.ui.hidden}
          widths={state.ui.widths}
          onClose={() => {
            setColumnsOpen(false);
            columnsButton.current?.focus();
          }}
          onHidden={(hidden) => commit(patchUi(stateRef.current, { hidden }), "push")}
          onWidth={(key, width, history) => commitWidth(key, width, history)}
          onReset={() => commit(patchUi(stateRef.current, { hidden: [] }), "push")}
        />
      ) : null}
      <fieldset className={styles.choice}>
        <legend>Density</legend>
        {(["comfortable", "compact"] as const).map((density) => (
          <label key={density}>
            <input
              type="radio"
              name="ui-density"
              value={density}
              checked={state.ui.density === density}
              onChange={() => commit(patchUi(stateRef.current, { density }), "push")}
            />
            {density === "comfortable" ? "Comfortable" : "Compact"}
          </label>
        ))}
      </fieldset>
      {hasPoints ? <p id="points-legend">{POINTS_LEGEND}</p> : null}
      {localEmpty ? (
        <p>
          {tableCopy.localEmpty}{" "}
          <button
            type="button"
            className={`${pageStyles.button} ${pageStyles.buttonSecondary}`}
            onClick={() => commit(patchUi(stateRef.current, { filters: {}, search: "" }), "push")}
          >
            {tableCopy.clearPageFilters}
          </button>
        </p>
      ) : null}
      {phase === "ready" ? (
        <DataTable
          data={filtered}
          columns={columns}
          getRowId={resource.rowId}
          sorting={sorting}
          onSortingChange={onSortingChange}
          columnFilters={columnFilters}
          onColumnFiltersChange={onColumnFiltersChange}
          manual
          density={state.ui.density}
        />
      ) : null}
      {full ? (
        <dialog
          ref={dialogRef}
          aria-label="Full value"
          onCancel={(event) => {
            event.preventDefault();
            closeFull();
          }}
        >
          <p>{full.label}</p>
          <p className={styles.fullText}>{full.value}</p>
          <button type="button" className={pageStyles.button} onClick={closeFull}>
            Close
          </button>
        </dialog>
      ) : null}
    </div>
  );
}

function SearchBox({ value, onCommit }: { value: string; onCommit: (value: string, history: HistoryMode) => void }) {
  const [draft, setDraft] = useState(value);
  const seeded = useRef(false);
  const commitRef = useRef(onCommit);
  commitRef.current = onCommit;
  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    const next = draft.trim();
    if (next === value) return;
    const timer = window.setTimeout(() => {
      commitRef.current(next, seeded.current ? "replace" : "push");
      seeded.current = true;
    }, 250);
    return () => window.clearTimeout(timer);
  }, [draft, value]);
  return (
    <label className={pageStyles.field}>
      {tableCopy.searchLabel}
      <input
        maxLength={100}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          const next = draft.trim();
          seeded.current = true;
          commitRef.current(next, "push");
        }}
        onBlur={() => {
          seeded.current = false;
        }}
      />
    </label>
  );
}

function FilterPanel({
  meta,
  rows,
  filter,
  onApply,
  onClose,
}: {
  meta: ColumnMeta;
  rows: Row[];
  filter: ColumnFilter | undefined;
  onApply: (filter: ColumnFilter | null, history: HistoryMode) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (meta.filter === "range") {
    return <RangeFields applied={filter?.kind === "range" ? filter : undefined} onApply={onApply} onClose={onClose} />;
  }
  if (meta.filter === "multi") {
    return <MultiFields meta={meta} rows={rows} applied={filter?.kind === "multi" ? filter : undefined} onApply={onApply} onClose={onClose} />;
  }
  return <TextFields applied={filter?.kind === "text" ? filter.value : ""} onApply={onApply} />;
}

function TextFields({ applied, onApply }: { applied: string; onApply: (filter: ColumnFilter | null, history: HistoryMode) => void }) {
  const [draft, setDraft] = useState(applied);
  const seeded = useRef(false);
  const applyRef = useRef(onApply);
  applyRef.current = onApply;
  useEffect(() => setDraft(applied), [applied]);
  useEffect(() => {
    const next = draft.trim();
    if (next === applied) return;
    const timer = window.setTimeout(() => {
      applyRef.current(next ? { kind: "text", value: next } : null, seeded.current ? "replace" : "push");
      seeded.current = true;
    }, 250);
    return () => window.clearTimeout(timer);
  }, [applied, draft]);
  return (
    <label className={pageStyles.field}>
      Text contains
      <input
        maxLength={100}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          const next = draft.trim();
          seeded.current = true;
          applyRef.current(next ? { kind: "text", value: next } : null, "push");
        }}
      />
    </label>
  );
}

function RangeFields({
  applied,
  onApply,
  onClose,
}: {
  applied: RangeFilter | undefined;
  onApply: (filter: ColumnFilter | null, history: HistoryMode) => void;
  onClose: () => void;
}) {
  const [min, setMin] = useState(applied?.min === null || applied?.min === undefined ? "" : String(applied.min));
  const [max, setMax] = useState(applied?.max === null || applied?.max === undefined ? "" : String(applied.max));
  const [guidance, setGuidance] = useState("");
  return (
    <div className={styles.panel}>
      <label className={pageStyles.field}>
        Minimum
        <input inputMode="decimal" value={min} aria-invalid={guidance !== ""} onChange={(event) => setMin(event.target.value)} />
      </label>
      <label className={pageStyles.field}>
        Maximum
        <input inputMode="decimal" value={max} aria-invalid={guidance !== ""} onChange={(event) => setMax(event.target.value)} />
      </label>
      {guidance ? <p className={styles.guidance}>{guidance}</p> : null}
      {applied ? <p>{`Applied range remains ${applied.min ?? "none"} to ${applied.max ?? "none"}.`}</p> : null}
      <button
        type="button"
        className={pageStyles.button}
        onClick={() => {
          const low = parseDecimalInput(min);
          const high = parseDecimalInput(max);
          if (low === "invalid" || high === "invalid" || (low !== null && high !== null && low > high)) {
            setGuidance("Enter a finite decimal without commas. Min cannot be greater than max.");
            return;
          }
          setGuidance("");
          onApply(low === null && high === null ? null : { kind: "range", min: low, max: high }, "push");
          onClose();
        }}
      >
        Apply
      </button>
    </div>
  );
}

function MultiFields({
  meta,
  rows,
  applied,
  onApply,
  onClose,
}: {
  meta: ColumnMeta;
  rows: Row[];
  applied: MultiFilter | undefined;
  onApply: (filter: ColumnFilter | null, history: HistoryMode) => void;
  onClose: () => void;
}) {
  const selected = applied?.values ?? [];
  const [values, setValues] = useState<string[]>(selected);
  const [missing, setMissing] = useState(applied?.missing ?? false);
  const options = multiOptions(rows, meta.key, selected);
  return (
    <div className={styles.panel}>
      {options.map((option) => (
        <label key={option} className={styles.choice}>
          <input
            type="checkbox"
            checked={values.includes(option)}
            onChange={(event) => {
              setValues((current) => (event.target.checked ? [...current, option] : current.filter((item) => item !== option)));
            }}
          />
          {option}
        </label>
      ))}
      <label className={styles.choice}>
        <input type="checkbox" checked={missing} onChange={(event) => setMissing(event.target.checked)} />
        Missing
      </label>
      <button
        type="button"
        className={pageStyles.button}
        onClick={() => {
          const next = [...new Set(values.map((value) => value.toLocaleUpperCase("en-US")))].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
          onApply(next.length === 0 && !missing ? null : { kind: "multi", values: next, missing }, "push");
          onClose();
        }}
      >
        Apply
      </button>
    </div>
  );
}

function SortPanel({
  resource,
  sort,
  onChange,
  onClose,
}: {
  resource: Resource;
  sort: PageUi["sort"];
  onChange: (sort: PageUi["sort"]) => void;
  onClose: () => void;
}) {
  const available = resource.columns.filter((key) => !sort.some((entry) => entry.id === key));
  const [column, setColumn] = useState(available[0] ?? resource.columns[0]);
  const [desc, setDesc] = useState(false);
  const chosen = available.includes(column) ? column : (available[0] ?? "");
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div id="sort-panel" role="region" aria-label="Sort" className={styles.panel}>
      {sort.map((entry, index) => (
        <div key={entry.id} className={styles.sortRow}>
          <span>{`${index + 1}. ${columnMeta(entry.id).label} ${entry.desc ? "descending" : "ascending"}`}</span>
          <button type="button" className={pageStyles.button} onClick={() => onChange(toggleSortDirection(sort, index))}>
            {entry.desc ? "Make ascending" : "Make descending"}
          </button>
          <button type="button" className={pageStyles.button} disabled={index === 0} onClick={() => onChange(moveSort(sort, index, -1))}>
            Move up
          </button>
          <button
            type="button"
            className={pageStyles.button}
            disabled={index === sort.length - 1}
            onClick={() => onChange(moveSort(sort, index, 1))}
          >
            Move down
          </button>
          <button type="button" className={pageStyles.button} onClick={() => onChange(removeSort(sort, index))}>
            {`Remove ${columnMeta(entry.id).label}`}
          </button>
        </div>
      ))}
      <label className={pageStyles.field}>
        Add column
        <select value={chosen} onChange={(event) => setColumn(event.target.value)}>
          {available.map((key) => (
            <option key={key} value={key}>
              {columnMeta(key).label}
            </option>
          ))}
        </select>
      </label>
      <label className={pageStyles.field}>
        Add direction
        <select value={desc ? "desc" : "asc"} onChange={(event) => setDesc(event.target.value === "desc")}>
          <option value="asc">Ascending</option>
          <option value="desc">Descending</option>
        </select>
      </label>
      <button
        type="button"
        className={pageStyles.button}
        disabled={sort.length >= 3 || available.length === 0}
        onClick={() => onChange(addSort(sort, chosen, desc))}
      >
        Add sort
      </button>
      {sort.length >= 3 ? <p>A fourth sort cannot be added. This page keeps at most three sort priorities.</p> : null}
    </div>
  );
}

function ColumnChooser({
  resource,
  hidden,
  widths,
  onHidden,
  onWidth,
  onReset,
  onClose,
}: {
  resource: Resource;
  hidden: string[];
  widths: Record<string, number>;
  onHidden: (hidden: string[]) => void;
  onWidth: (key: string, width: number, history: HistoryMode) => void;
  onReset: () => void;
  onClose: () => void;
}) {
  const hiddenSet = new Set(hidden);
  const visibleCount = resource.columns.length - hiddenSet.size;
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div id="column-chooser" role="region" aria-label="Columns" className={styles.panel}>
      {resourceColumns(resource).map((meta) => {
        const visible = !hiddenSet.has(meta.key);
        return (
          <div key={meta.key} className={styles.choice}>
            <label>
              <input
                type="checkbox"
                checked={visible}
                disabled={visible && visibleCount === 1}
                onChange={() => {
                  if (visible && visibleCount === 1) return;
                  const next = new Set(hidden);
                  if (visible) next.add(meta.key);
                  else next.delete(meta.key);
                  onHidden([...next]);
                }}
              />
              {meta.label} <span className={styles.key}>{meta.key}</span>
            </label>
            <WidthInput label={meta.label} value={widths[meta.key] ?? meta.width} onWidth={(width, history) => onWidth(meta.key, width, history)} />
          </div>
        );
      })}
      {visibleCount === 1 ? <p>At least one column stays visible.</p> : null}
      <button type="button" className={pageStyles.button} onClick={onReset}>
        Reset columns
      </button>
    </div>
  );
}

function WidthInput({ label, value, onWidth }: { label: string; value: number; onWidth: (width: number, history: HistoryMode) => void }) {
  const [draft, setDraft] = useState(String(value));
  const [invalid, setInvalid] = useState(false);
  const seeded = useRef(false);
  useEffect(() => setDraft(String(value)), [value]);
  function parse(text: string): number | null {
    if (!/^\d{2,3}$/.test(text)) return null;
    const number = Number(text);
    if (!Number.isInteger(number) || number < 96 || number > 480) return null;
    return number;
  }
  return (
    <label className={pageStyles.field}>
      {`Width of ${label}`}
      <input
        inputMode="numeric"
        min={96}
        max={480}
        step={1}
        value={draft}
        aria-invalid={invalid}
        onFocus={() => {
          seeded.current = false;
        }}
        onChange={(event) => {
          const next = event.target.value;
          setDraft(next);
          const parsed = parse(next);
          setInvalid(next !== "" && parsed === null);
          if (parsed === null || parsed === value) return;
          onWidth(parsed, seeded.current ? "replace" : "push");
          seeded.current = true;
        }}
        onBlur={() => {
          const parsed = parse(draft);
          if (parsed === null) {
            setInvalid(true);
            setDraft(String(value));
            return;
          }
          setInvalid(false);
        }}
      />
      {invalid ? <span className={styles.guidance}>Width must be a whole number from 96 to 480.</span> : null}
    </label>
  );
}

function FilterChips({
  resource,
  ui,
  onRemove,
}: {
  resource: Resource;
  ui: PageUi;
  onRemove: (key: string, value?: string) => void;
}) {
  const chips: { id: string; text: string; key: string; value?: string }[] = [];
  if (ui.search) chips.push({ id: "search", text: `Search: ${ui.search}`, key: "search" });
  for (const [key, filter] of Object.entries(ui.filters)) {
    const label = columnMeta(key).label;
    if (!resource.columns.includes(key)) continue;
    if (filter.kind === "text") chips.push({ id: key, text: `${label}: ${filter.value}`, key });
    if (filter.kind === "range") {
      const low = filter.min === null ? "" : String(filter.min);
      const high = filter.max === null ? "" : String(filter.max);
      chips.push({ id: key, text: `${label}: ${low || "…"} to ${high || "…"}`, key });
    }
    if (filter.kind === "multi") {
      for (const value of filter.values) chips.push({ id: `${key}-${value}`, text: `${label}: ${value}`, key, value });
      if (filter.missing) chips.push({ id: `${key}-missing`, text: `${label}: Missing`, key, value: "missing" });
    }
  }
  if (chips.length === 0) return null;
  return (
    <ul className={styles.chips} aria-label="Active page filters">
      {chips.map((chip) => (
        <li key={chip.id} className={styles.chip}>
          <span>{chip.text}</span>
          <button type="button" onClick={() => onRemove(chip.key, chip.value)}>
            {`Remove ${chip.text}`}
          </button>
        </li>
      ))}
    </ul>
  );
}
