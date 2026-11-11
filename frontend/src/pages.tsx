import { useEffect, useState } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnFiltersState, OnChangeFn, SortingState } from "@tanstack/react-table";
import type { LegacyColumnDef } from "@tanstack/react-table/legacy";
import { ApiError, cellText, getList, metaProblem, useApiMeta, type Row, type Search } from "./api";
import { DataTable } from "./DataTable";
import { AppLink, MetaError } from "./shell";
import { currentSort, pageLinks, pagerSearch, parseSearch, sortSearch, toHref, type Resource } from "./resources";
import styles from "./pages.module.css";

function useTitle(title: string) {
  useEffect(() => {
    document.title = title;
    document.getElementById("page-title")?.focus();
  }, [title]);
}

export function HomePage() {
  useTitle("Seam Finder");
  const meta = useApiMeta();
  return (
    <div className={styles.stack}>
      <h1 id="page-title" tabIndex={-1}>
        Seam Finder
      </h1>
      <ul className={styles.links}>
        {pageLinks.map((page) => (
          <li key={page.href}>
            <AppLink href={page.href} plain>
              {page.label}
            </AppLink>
          </li>
        ))}
      </ul>
      <MetaError />
      <h2>Last refresh per dataset</h2>
      <ul className={styles.cards}>
        {(meta.data?.datasets ?? []).map((item) => (
          <li key={item.dataset} className={styles.card}>
            {item.dataset}: {item.finished_at}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function NotFoundPage() {
  useTitle("Seam Finder");
  return (
    <div className={styles.stack}>
      <h1 id="page-title" tabIndex={-1}>
        Seam Finder
      </h1>
      <p role="alert" className={styles.alert}>
        Not found
      </p>
      <MetaError />
      <p>
        <AppLink href="/" plain>
          Home
        </AppLink>
      </p>
    </div>
  );
}

function usePageSearch(): Search {
  return parseSearch(useSearch({ strict: false }));
}

function listMessage(error: unknown, isError: boolean): string | null {
  if (!isError) return null;
  if (error instanceof ApiError) return error.message;
  return "Something went wrong.";
}

export function TablePage({ resource }: { resource: Resource }) {
  useTitle(resource.title);
  const search = usePageSearch();
  const navigate = useNavigate();
  const meta = useApiMeta();
  const searchKey = JSON.stringify(search);
  const [draft, setDraft] = useState<Search>(search);
  const [submitted, setSubmitted] = useState(false);
  useEffect(() => {
    setDraft(JSON.parse(searchKey) as Search);
  }, [searchKey]);
  const list = useQuery({
    queryKey: ["list", resource.apiPath, search],
    queryFn: () => getList(resource.apiPath, search),
    placeholderData: keepPreviousData,
  });
  const error = listMessage(list.error, list.isError);
  const metaError = metaProblem(meta.error, meta.isError, meta.isPending);
  const { sort, order } = currentSort(search, resource);
  const sorting: SortingState = [{ id: sort, desc: order === "desc" }];
  const columnFilters: ColumnFiltersState = [];
  const onSortingChange: OnChangeFn<SortingState> = () => undefined;
  const onColumnFiltersChange: OnChangeFn<ColumnFiltersState> = () => undefined;
  const columns: LegacyColumnDef<Row>[] = resource.columns.map((name) => ({
    id: name,
    accessorKey: name,
    header:
      error || !resource.sorts.includes(name)
        ? name
        : () => (
            <AppLink href={toHref(resource.pagePath, sortSearch(search, resource, name))} plain>
              {name}
            </AppLink>
          ),
    cell: (info) => cellText(info.getValue()),
    enableSorting: resource.sorts.includes(name),
  }));

  const total = list.data?.page.total ?? 0;
  const offset = list.data?.page.offset ?? 0;
  const limit = list.data?.page.limit ?? 50;
  const count = list.data?.data.length ?? 0;
  const start = !list.data || total === 0 ? 0 : offset + 1;
  const end = !list.data || total === 0 ? 0 : offset + count;
  const nextOffset = offset + limit;
  const prevOffset = Math.max(0, offset - limit);
  const showSkeleton = list.isPending;
  const showTable = !showSkeleton && !error && Boolean(list.data);
  const beyondPage = showTable && count === 0 && offset > 0 && total > 0;
  const noResults = showTable && total === 0;
  let live = "";
  if (showSkeleton) live = "Loading data";
  else if (showTable && list.isFetching) live = "Updating data";
  else if (submitted && list.isSuccess) live = "Results updated";

  return (
    <div className={styles.stack}>
      <h1 id="page-title" tabIndex={-1}>
        {resource.title}
      </h1>
      {error ? (
        <div role="alert" className={styles.alert}>
          <p>{error}</p>
          <button type="button" className={`${styles.button} ${styles.buttonSecondary}`} onClick={() => void list.refetch()}>
            Retry
          </button>
        </div>
      ) : null}
      {metaError && metaError !== error ? <MetaError /> : null}
      <form
        className={styles.form}
        method="get"
        action={resource.pagePath}
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(true);
          const data = new FormData(event.currentTarget);
          const next: Search = {};
          for (const [key, value] of data.entries()) {
            if (typeof value === "string" && value !== "") next[key] = value;
          }
          void navigate({ href: toHref(resource.pagePath, next) });
        }}
      >
        {resource.filters.map((field) => (
          <label key={field.name} className={styles.field}>
            {field.label}
            <input
              type="text"
              name={field.name}
              value={draft[field.name] ?? ""}
              onChange={(event) => setDraft((current) => ({ ...current, [field.name]: event.target.value }))}
            />
          </label>
        ))}
        <input type="hidden" name="sort" value={sort} />
        <input type="hidden" name="order" value={order} />
        <button className={styles.button} type="submit">
          Filter
        </button>
      </form>
      <p className={styles.status} aria-live="polite">
        {live}
      </p>
      {showSkeleton ? (
        <div className={styles.region} role="region" aria-label={resource.title} aria-busy="true">
          <table className={styles.skeleton} aria-hidden="true">
            <tbody>
              {Array.from({ length: 8 }, (_, index) => (
                <tr key={index}>
                  <td />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {showTable ? (
        <div className={styles.region} role="region" aria-label={resource.title} aria-busy={list.isFetching}>
          <DataTable
            data={list.data?.data ?? []}
            columns={columns}
            getRowId={resource.rowId}
            sorting={sorting}
            onSortingChange={onSortingChange}
            columnFilters={columnFilters}
            onColumnFiltersChange={onColumnFiltersChange}
            manual
          />
          {noResults ? (
            <p>
              No results for these filters.{" "}
              <button
                type="button"
                className={`${styles.button} ${styles.buttonSecondary}`}
                onClick={() => {
                  setSubmitted(true);
                  void navigate({ href: resource.pagePath });
                }}
              >
                Clear filters
              </button>
            </p>
          ) : null}
          {beyondPage ? (
            <p>
              No rows on this page.{" "}
              <AppLink href={toHref(resource.pagePath, pagerSearch(search, resource, 0))} plain>
                First page
              </AppLink>
            </p>
          ) : null}
          <p className={styles.pager}>rows {start}-{end} of {total}</p>
          <p className={styles.pager}>
            {offset > 0 ? (
              <AppLink href={toHref(resource.pagePath, pagerSearch(search, resource, prevOffset))} plain>
                Previous
              </AppLink>
            ) : null}{" "}
            {nextOffset < total ? (
              <AppLink href={toHref(resource.pagePath, pagerSearch(search, resource, nextOffset))} plain>
                Next
              </AppLink>
            ) : null}
          </p>
        </div>
      ) : null}
    </div>
  );
}
