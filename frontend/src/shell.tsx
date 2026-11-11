import { useEffect, useId, useState, type ReactNode } from "react";
import { Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { ATTRIBUTION_LINKS, ATTRIBUTION_TEXT } from "./attribution";
import { metaProblem, useApiMeta } from "./api";
import { pageLinks } from "./resources";
import styles from "./shell.module.css";

const navLinks = [{ href: "/", label: "Home" }, ...pageLinks];

function useWide(): boolean {
  const [wide, setWide] = useState(true);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(min-width: 1024px)");
    const apply = () => setWide(query.matches);
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, []);
  return wide;
}

export function AppLink({
  href,
  children,
  current = false,
  className,
  plain = false,
  onNavigate,
}: {
  href: string;
  children: ReactNode;
  current?: boolean;
  className?: string;
  plain?: boolean;
  onNavigate?: () => void;
}) {
  const navigate = useNavigate();
  return (
    <a
      href={href}
      className={plain ? className : (className ?? styles.link)}
      aria-current={current ? "page" : undefined}
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
        onNavigate?.();
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
    <footer id="attribution" className={styles.footer}>
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
  return (
    <div role="alert" className={styles.alert}>
      <p>{message}</p>
      <button type="button" onClick={() => void meta.refetch()}>
        Retry
      </button>
    </div>
  );
}

export function Shell() {
  const wide = useWide();
  const [open, setOpen] = useState(false);
  const navId = useId();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const showNav = wide || open;

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setOpen(false);
      document.getElementById("nav-toggle")?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <div className={styles.shell}>
        <header className={styles.header}>
          <button
            id="nav-toggle"
            type="button"
            className={styles.menu}
            aria-expanded={open}
            aria-controls={navId}
            hidden={wide}
            onClick={() => setOpen((value) => !value)}
          >
            Menu
          </button>
          <AppLink href="/" className={styles.brand}>
            Seam Finder
          </AppLink>
        </header>
        <nav
          id={navId}
          className={showNav ? styles.nav : `${styles.nav} ${styles.navClosed}`}
          aria-label="Primary"
        >
          <AppLink href="/" className={styles.brand}>
            Seam Finder
          </AppLink>
          <ul className={styles.list}>
            {navLinks.map((link) => {
              const current = pathname === link.href;
              return (
                <li key={link.href}>
                  <AppLink
                    href={link.href}
                    current={current}
                    onNavigate={() => setOpen(false)}
                  >
                    <span>{link.label}</span>
                    {current ? (
                      <span className={styles.marker} aria-hidden="true">
                        Current
                      </span>
                    ) : null}
                  </AppLink>
                </li>
              );
            })}
          </ul>
        </nav>
        <main id="main" tabIndex={-1} className={styles.main}>
          <Outlet />
        </main>
        <Footer />
      </div>
    </>
  );
}
