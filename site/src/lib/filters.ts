export const FILTER_KEYS = [
  "q",
  "area",
  "stars",
  "near_metro",
  "max_total",
  "checkin",
  "nights",
  "limit",
  "offset",
] as const;
export type Filters = Partial<Record<(typeof FILTER_KEYS)[number], string>>;
export function parse(params: URLSearchParams): Filters {
  const out: Filters = {};
  for (const key of FILTER_KEYS) {
    const value = params.get(key)?.trim().slice(0, 100);
    if (value) out[key] = value;
  }
  return out;
}
export function serialize(filters: Filters) {
  return new URLSearchParams(Object.entries(filters).filter(([, v]) => v.trim())).toString();
}
export function setUrl(key: string, value: string | null) {
  const url = new URL(window.location.href);
  if (value) url.searchParams.set(key, value);
  else url.searchParams.delete(key);
  window.history.pushState(null, "", url);
  window.dispatchEvent(new Event("rt-url"));
}
