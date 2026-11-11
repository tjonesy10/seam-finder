import type { ReactNode } from "react";
import { Outlet, useNavigate } from "@tanstack/react-router";
import { ATTRIBUTION_LINKS, ATTRIBUTION_TEXT } from "./attribution";
import { metaProblem, useApiMeta } from "./api";

export function AppLink({ href, children }: { href: string; children: ReactNode }) {
  const navigate = useNavigate();
  return (
    <a
      href={href}
      onClick={(event) => {
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        ) {
          return;
        }
        event.preventDefault();
        void navigate({ href });
      }}
    >
      {children}
    </a>
  );
}

export function refreshLabel(value: string | undefined, ready: boolean): string {
  if (!ready || !value) return "none";
  return value;
}

export function Footer() {
  const meta = useApiMeta();
  const label = refreshLabel(meta.data?.last_refresh_et, meta.isSuccess);
  return (
    <footer>
      <p>{ATTRIBUTION_TEXT}</p>
      <ul>
        {ATTRIBUTION_LINKS.map((link) => (
          <li key={link.url}>
            <a href={link.url}>{link.label}</a>
          </li>
        ))}
      </ul>
      <p>Last refresh: {label}</p>
    </footer>
  );
}

export function MetaError() {
  const meta = useApiMeta();
  const message = metaProblem(meta.error, meta.isError, meta.isPending);
  if (!message) return null;
  return <p className="error">{message}</p>;
}

export function Shell() {
  return (
    <>
      <p>
        <AppLink href="/">Seam Finder</AppLink>
      </p>
      <Outlet />
      <Footer />
    </>
  );
}
