import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

// Modulweiter Cache + In-Flight-Dedup. Verhindert, dass jeder Routenwechsel
// denselben Endpunkt neu lädt und dass parallele Mounts denselben Request
// mehrfach abschicken (stale-while-revalidate).
type CacheEntry = { data: unknown };
const cache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<unknown>>();

function fetchDedup(path: string): Promise<unknown> {
  const existing = inflight.get(path);
  if (existing) return existing;
  const p = api
    .get(path)
    .then((d) => {
      cache.set(path, { data: d });
      return d;
    })
    .finally(() => inflight.delete(path));
  inflight.set(path, p);
  return p;
}

// Cache eines Pfads (oder alles) verwerfen – z. B. nach einer Mutation.
export function invalidate(path?: string) {
  if (path) cache.delete(path);
  else cache.clear();
}

// Lädt einen GET-Endpunkt; liefert Daten, Ladezustand und ein reload().
// reload() erzwingt einen frischen Request; beim Mount werden gecachte Daten
// sofort gezeigt und im Hintergrund revalidiert.
export function useApiData<T>(path: string | null) {
  const initial = path ? (cache.get(path)?.data as T | undefined) : undefined;
  const [data, setData] = useState<T | null>(initial ?? null);
  const [loading, setLoading] = useState(initial === undefined);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (force: boolean) => {
      if (!path) return;
      const hit = cache.get(path);
      if (hit && !force) {
        setData(hit.data as T);
        setLoading(false);
      } else {
        setLoading(true);
      }
      setError(null);
      fetchDedup(path)
        .then((d) => setData(d as T))
        .catch((e) => {
          // Bei vorhandenem Cache still revalidieren (alte Daten weiter zeigen).
          if (!hit) setError((e as { code?: string })?.code ?? "error");
        })
        .finally(() => setLoading(false));
    },
    [path],
  );

  useEffect(() => load(false), [load]);

  const reload = useCallback(() => load(true), [load]);

  return { data, loading, error, reload };
}
