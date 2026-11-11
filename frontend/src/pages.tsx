import { useEffect } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import type { ColumnFiltersState, OnChangeFn, SortingState } from "@tanstack/react-table";
import type { LegacyColumnDef } from "@tanstack/react-table/legacy";
import { ApiError, cellText, getList, metaProblem, useApiMeta, type Row, type Search } from "./api";
import { DataTable } from "./DataTable";
import { AppLink, MetaError } from "./shell";
import { currentSort, pageLinks, pagerSearch, parseSearch, sortSearch, toHref, type Resource } from "./resources";

function useTitle(title: string) {
  useEffect(() => {
    document.title = title;
  }, [title]);
}

export function HomePage() {
  useTitle("Seam Finder");
  const meta = useApiMeta();
  return (
    <>
      <h1>Seam Finder</h1>
      <ul>
        {pageLinks.map((page) => (
          <li key={page.href}>
            <AppLink href={page.href}>{page.label}</AppLink>
          </li>
        ))}
      </ul>
      <MetaError />
      <h2>Last refresh per dataset</h2>
      <ul>
        {(meta.data?.datasets ?? []).map((item) => (
          <li key={item.dataset}>
            {item.dataset}: {item.finished_at}
          </li>
        ))}
      </ul>
    </>
  );
}

export function NotFoundPage() {
  useTitle("Seam Finder");
  return (
    <>
      <h1>Seam Finder</h1>
      <p className="error">Not found</p>
      <MetaError />
    </>
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
  const list = useQuery({
    queryKey: ["list", resource.apiPath, search],
    queryFn: () => getList(resource.apiPath, search),
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
    header: error || !resource.sorts.includes(name) ? name : () => (
      <AppLink href={toHref(resource.pagePath, sortSearch(search, resource, name))}>{name}</AppLink>
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

  return (
    <>
      <h1>{resource.title}</h1>
      {error ? <p className="error">{error}</p> : null}
      {metaError && metaError !== error ? <p className="error">{metaError}</p> : null}
      <form
        key={resource.pagePath + JSON.stringify(search)}
        method="get"
        action={resource.pagePath}
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const next: Search = {};
          for (const [key, value] of data.entries()) {
            if (typeof value === "string" && value !== "") next[key] = value;
          }
          void navigate({ href: toHref(resource.pagePath, next) });
        }}
      >
        {resource.filters.map((field) => (
          <label key={field.name}>
            {field.label}
            <input type="text" name={field.name} defaultValue={search[field.name] ?? ""} />
          </label>
        ))}
        <input type="hidden" name="sort" value={sort} />
        <input type="hidden" name="order" value={order} />
        <button type="submit">Filter</button>
      </form>
      <DataTable
        data={error ? [] : (list.data?.data ?? [])}
        columns={columns}
        getRowId={resource.rowId}
        sorting={sorting}
        onSortingChange={onSortingChange}
        columnFilters={columnFilters}
        onColumnFiltersChange={onColumnFiltersChange}
        manual
      />
      {error || !list.data ? null : (
        <>
          <p className="pager">
            rows {start}-{end} of {total}
          </p>
          <p className="pager">
            {offset > 0 ? (
              <AppLink href={toHref(resource.pagePath, pagerSearch(search, resource, prevOffset))}>Previous</AppLink>
            ) : null}{" "}
            {nextOffset < total ? (
              <AppLink href={toHref(resource.pagePath, pagerSearch(search, resource, nextOffset))}>Next</AppLink>
            ) : null}
          </p>
        </>
      )}
    </>
  );
}
