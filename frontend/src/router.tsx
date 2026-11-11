import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  type RouterHistory,
} from "@tanstack/react-router";
import { HomePage, NotFoundPage, TablePage } from "./pages";
import { games, loadRuns, parseSearch, players, stats, teams } from "./resources";
import { Shell } from "./shell";

const rootRoute = createRootRoute({
  component: Shell,
  notFoundComponent: NotFoundPage,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: parseSearch,
  component: HomePage,
});

function tableRoute(path: string, resource: typeof teams) {
  return createRoute({
    getParentRoute: () => rootRoute,
    path,
    validateSearch: parseSearch,
    component: () => <TablePage resource={resource} />,
  });
}

const routeTree = rootRoute.addChildren([
  indexRoute,
  tableRoute("/teams", teams),
  tableRoute("/players", players),
  tableRoute("/games", games),
  tableRoute("/stats", stats),
  tableRoute("/load-runs", loadRuns),
]);

function stringifySearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (value === undefined || value === null || value === "") continue;
    params.append(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

function parseRouterSearch(searchStr: string): Record<string, unknown> {
  const query = searchStr.startsWith("?") ? searchStr.slice(1) : searchStr;
  const params = new URLSearchParams(query);
  const result: Record<string, string> = {};
  for (const [key, value] of params.entries()) result[key] = value;
  return result;
}

export function createAppRouter(history?: RouterHistory) {
  return createRouter({
    routeTree,
    history,
    defaultNotFoundComponent: NotFoundPage,
    stringifySearch,
    parseSearch: parseRouterSearch,
  });
}

export function memoryHistory(path: string): RouterHistory {
  return createMemoryHistory({ initialEntries: [path] });
}

export type AppRouter = ReturnType<typeof createAppRouter>;

declare module "@tanstack/react-router" {
  interface Register {
    router: AppRouter;
  }
}
