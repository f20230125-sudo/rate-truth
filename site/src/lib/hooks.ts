"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import { ApiError } from "./api";
const subscribe = (callback: () => void) => {
  window.addEventListener("popstate", callback);
  window.addEventListener("rt-url", callback);
  return () => {
    window.removeEventListener("popstate", callback);
    window.removeEventListener("rt-url", callback);
  };
};
export function useQuery() {
  return useSyncExternalStore(
    subscribe,
    () => window.location.search,
    () => "",
  );
}
export function errorMessage(error: unknown) {
  if (error instanceof ApiError && error.status === 429) {
    const seconds = error.retryAfter ?? 60;
    const retryAt = new Date(Date.now() + seconds * 1000).toLocaleTimeString();
    return (
      `Rate limit reached. Ask again after ${retryAt} (in ${seconds} seconds). ` +
      "Replay remains available when the limit resets."
    );
  }
  return error instanceof Error ? error.message : "The API could not be reached.";
}
export function useData<T>(loader: (signal: AbortSignal) => Promise<T>) {
  const [state, setState] = useState<{ data?: T; error?: string }>({});
  useEffect(() => {
    const controller = new AbortController();
    loader(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ data });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState({ error: errorMessage(error) });
      });
    return () => controller.abort();
  }, [loader]);
  return state;
}
