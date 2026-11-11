import { useEffect, useRef, useState } from "react";
import { useNavigate, useRouterState, useSearch } from "@tanstack/react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ApiError, getList, metaProblem, useApiMeta, type Row, type Search } from "./api";
import { PremiumTable } from "./PremiumTable";
import { listRequest, normalizeTableSearch, parseLimit, readTableState, searchRecord, withDatasetForm, withOffset, writeTableState, type TableState } from "./pageState";
import { AppLink, MetaError } from "./shell";
import { pageLinks, toHref, type Resource } from "./resources";
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

function listMessage(error: unknown, isError: boolean): string | null {
  if (!isError) return null;
  if (error instanceof ApiError) return error.message;
  return "Something went wrong.";
}

export function TablePage({ resource }: { resource: Resource }) {
  useTitle(resource.title);
  const search = useSearch({ strict: false });
  const state = readTableState(search, resource);
  const navigate = useNavigate();
  const searchStr = useRouterState({ select: (router) => router.location.searchStr });
  const meta = useApiMeta();
  const appliedKey = JSON.stringify(state.filters);
  const [draft, setDraft] = useState<Search>(state.filters);
  const [limitDraft, setLimitDraft] = useState(String(state.limit));
  const [limitError, setLimitError] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  useEffect(() => {
    setDraft(JSON.parse(appliedKey) as Search);
  }, [appliedKey]);
  useEffect(() => {
    setLimitDraft(String(state.limit));
  }, [state.limit]);
  const canonical = toHref(resource.pagePath, normalizeTableSearch(searchRecord(searchStr), resource));
  const current = `${resource.pagePath}${searchStr}`;
  useEffect(() => {
    if (canonical === current) return;
    void navigate({ href: canonical, replace: true });
  }, [canonical, current, navigate]);
  const request = listRequest(resource, state);
  const list = useQuery({
    queryKey: request.queryKey,
    queryFn: () => getList(resource.apiPath, request.search),
    placeholderData: keepPreviousData,
  });
  const error = listMessage(list.error, list.isError);
  const metaError = metaProblem(meta.error, meta.isError, meta.isPending);

  function commit(next: TableState, history: "push" | "replace") {
    const href = toHref(resource.pagePath, writeTableState(next, resource));
    if (href === `${resource.pagePath}${searchStr}`) return;
    void navigate({ href, replace: history === "replace" });
  }

  const total = list.data?.page.total ?? 0;
  const offset = list.data?.page.offset ?? 0;
  const limit = list.data?.page.limit ?? state.limit;
  const count = list.data?.data.length ?? 0;
  const start = !list.data || total === 0 ? 0 : offset + 1;
  const end = !list.data || total === 0 ? 0 : offset + count;
  const nextOffset = offset + limit;
  const prevOffset = Math.max(0, offset - limit);
  const showSkeleton = list.isPending && !list.data;
  const showTable = !showSkeleton && !error && Boolean(list.data);
  const beyondPage = showTable && count === 0 && offset > 0 && total > 0;
  const noResults = showTable && total === 0;
  const fresh = !list.isFetching && !list.isPlaceholderData && !error;
  let live = "";
  if (showSkeleton) live = "Loading data";
  else if (showTable && list.isFetching) live = "Updating data";
  else if (submitted && list.isSuccess && !list.isFetching) live = "Results updated";
  const loadedRows = showTable ? (list.data?.data ?? []) : [];
  const successfulRows = useRef<Row[] | null>(null);
  if (fresh && list.data) successfulRows.current = list.data.data;

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
      <div className={styles.dataset}>
        <form
          className={styles.form}
          method="get"
          action={resource.pagePath}
          onSubmit={(event) => {
            event.preventDefault();
            setSubmitted(true);
            const data = new FormData(event.currentTarget);
            const input: Search = {};
            for (const field of resource.filters) {
              const value = data.get(field.name);
              if (typeof value === "string") input[field.name] = value;
            }
            const limitValue = data.get("limit");
            const sortValue = data.get("dataset_sort");
            const orderValue = data.get("dataset_order");
            if (typeof limitValue === "string") input.limit = limitValue;
            if (typeof sortValue === "string") input.sort = sortValue;
            if (typeof orderValue === "string") input.order = orderValue;
            commit(withDatasetForm(state, resource, input), "push");
          }}
        >
          <fieldset>
            <legend>Dataset filters</legend>
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
            <label className={styles.field}>
              Page size
              <input
                name="limit"
                inputMode="numeric"
                value={limitDraft}
                aria-invalid={limitError}
                onChange={(event) => setLimitDraft(event.target.value)}
                onBlur={() => {
                  const parsed = parseLimit(limitDraft);
                  if (parsed === null) {
                    setLimitError(true);
                    setLimitDraft(String(state.limit));
                    return;
                  }
                  setLimitError(false);
                  if (parsed !== state.limit) commit({ ...state, limit: parsed, offset: 0 }, "push");
                }}
              />
            </label>
            {limitError ? <p className={styles.status}>Page size must be a whole number from 1 to 500.</p> : null}
            <button className={styles.button} type="submit">
              Filter
            </button>
          </fieldset>
          <fieldset>
            <legend>Dataset order</legend>
            <label className={styles.field}>
              Dataset order field
              <select
                name="dataset_sort"
                value={state.sort}
                onChange={(event) => commit({ ...state, sort: event.target.value, offset: 0 }, "push")}
              >
                {resource.sorts.map((sort) => (
                  <option key={sort} value={sort}>
                    {sort}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.field}>
              Dataset order direction
              <select
                name="dataset_order"
                value={state.order}
                onChange={(event) => {
                  const order = event.target.value === "desc" ? "desc" : "asc";
                  commit({ ...state, order, offset: 0 }, "push");
                }}
              >
                <option value="asc">Ascending</option>
                <option value="desc">Descending</option>
              </select>
            </label>
          </fieldset>
        </form>
      </div>
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
      <PremiumTable
        resource={resource}
        rows={loadedRows}
        successfulRows={successfulRows.current}
        state={state}
        phase={error ? "error" : showSkeleton ? "loading" : "ready"}
        fresh={fresh}
        onState={commit}
      />
      {showTable ? (
        <div className={styles.region} role="region" aria-label={`${resource.title} pages`} aria-busy={list.isFetching}>
          {noResults ? (
            <p>
              No results for these filters.{" "}
              <button
                type="button"
                className={`${styles.button} ${styles.buttonSecondary}`}
                onClick={() => {
                  setSubmitted(true);
                  commit({ ...state, filters: {}, sort: resource.defaultSort, order: resource.defaultOrder, limit: 50, offset: 0 }, "push");
                }}
              >
                Clear filters
              </button>
            </p>
          ) : null}
          {beyondPage ? (
            <p>
              No rows on this page.{" "}
              <AppLink href={toHref(resource.pagePath, writeTableState(withOffset(state, 0), resource))} plain>
                First page
              </AppLink>
            </p>
          ) : null}
          <p className={styles.pager}>rows {start}-{end} of {total}</p>
          <p className={styles.pager}>
            {offset > 0 ? (
              <AppLink href={toHref(resource.pagePath, writeTableState(withOffset(state, prevOffset), resource))} plain>
                Previous
              </AppLink>
            ) : null}{" "}
            {nextOffset < total ? (
              <AppLink href={toHref(resource.pagePath, writeTableState(withOffset(state, nextOffset), resource))} plain>
                Next
              </AppLink>
            ) : null}
          </p>
        </div>
      ) : null}
    </div>
  );
}
