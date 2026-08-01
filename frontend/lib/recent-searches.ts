"use client";

import * as React from "react";

/**
 * Recent company names only, exposed as an external store so components can
 * read it through `useSyncExternalStore` instead of hydrating in an effect.
 * Generated briefs are never persisted.
 */
const STORAGE_KEY = "company-intelligence:recent-companies";
const MAX_ENTRIES = 6;
const EMPTY: string[] = [];

const listeners = new Set<() => void>();
let cachedRaw: string | null = null;
let cachedValue: string[] = EMPTY;

function parse(raw: string | null): string[] {
  if (!raw) return EMPTY;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return EMPTY;
    const names = parsed.filter(
      (entry): entry is string => typeof entry === "string" && entry.trim().length > 0,
    );
    return names.length > 0 ? names.slice(0, MAX_ENTRIES) : EMPTY;
  } catch {
    return EMPTY;
  }
}

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode, blocked cookies).
    return null;
  }
}

/** Snapshot must be referentially stable between reads or React will loop. */
function getSnapshot(): string[] {
  const raw = readRaw();
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cachedValue = parse(raw);
  }
  return cachedValue;
}

function getServerSnapshot(): string[] {
  return EMPTY;
}

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange);
  // Keep tabs in sync when another one records a search.
  window.addEventListener("storage", onStoreChange);
  return () => {
    listeners.delete(onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

export function addRecentSearch(company: string): void {
  const name = company.trim();
  if (typeof window === "undefined" || !name) return;

  const current = parse(readRaw());
  const next = [name, ...current.filter((e) => e.toLowerCase() !== name.toLowerCase())].slice(
    0,
    MAX_ENTRIES,
  );
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    return;
  }
  listeners.forEach((listener) => listener());
}

export function useRecentSearches(): string[] {
  return React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
