import type { RouteRule, UnmatchedItem, UnmatchedTourMember } from "@/lib/api";

/** Một dòng rule: mọi từ sau dấu phẩy phải cùng có trong tên tour (AND). */
export function parseRouteKeywordList(keywords: string): string[] {
  return keywords
    .split(",")
    .map((k) => k.trim().toLowerCase())
    .filter(Boolean);
}

export function mergeRouteKeywordLists(existing: string, add: string): string {
  const set = new Set(parseRouteKeywordList(existing));
  for (const p of parseRouteKeywordList(add)) set.add(p);
  return [...set].join(", ");
}

const SPLIT_STORAGE_KEY = "ota-rules-unmatched-splits";

type SplitScope = "market" | "route";

type SplitStore = Partial<Record<SplitScope, string[]>>;

function readStore(): SplitStore {
  try {
    return JSON.parse(localStorage.getItem(SPLIT_STORAGE_KEY) || "{}") as SplitStore;
  } catch {
    return {};
  }
}

function writeStore(store: SplitStore) {
  localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(store));
}

export function loadUnmatchedSplits(scope: SplitScope): Set<string> {
  return new Set(readStore()[scope] ?? []);
}

export function splitUnmatchedTitle(scope: SplitScope, title: string) {
  const store = readStore();
  const set = new Set(store[scope] ?? []);
  set.add(title);
  store[scope] = [...set];
  writeStore(store);
}

export function unsplitUnmatchedTitle(scope: SplitScope, title: string) {
  const store = readStore();
  const set = new Set(store[scope] ?? []);
  set.delete(title);
  store[scope] = [...set];
  writeStore(store);
}

function memberSum(members: UnmatchedTourMember[]) {
  return members.reduce((s, m) => s + m.count, 0);
}

/** Tách tour đã chọn ra dòng riêng; nhóm còn lại giữ nguyên bucket. */
export function expandUnmatchedWithSplits(
  items: UnmatchedItem[],
  splitTitles: Set<string>,
): UnmatchedItem[] {
  const out: UnmatchedItem[] = [];
  for (const item of items) {
    const members = item.members ?? [];
    const canSplit = members.length > 1 || (item.grouped && item.count > 1);
    if (!canSplit || !splitTitles.size) {
      out.push(item);
      continue;
    }
    const split = members.filter((m) => splitTitles.has(m.title));
    const kept = members.filter((m) => !splitTitles.has(m.title));
    if (kept.length) {
      out.push({
        ...item,
        count: memberSum(kept) || item.count - memberSum(split),
        members: kept,
        grouped: kept.length > 1 || item.grouped,
      });
    }
    for (const m of split) {
      out.push({
        ...item,
        value: m.title,
        sample: m.title,
        count: m.count,
        grouped: false,
        keyword: "",
        members: [m],
        bucket_key: `split:${m.title}`,
      });
    }
    if (!kept.length && !split.length) out.push(item);
  }
  return out;
}

export type RouteKeywordConflict = {
  keyword: string;
  routes: { thi_truong: string; tuyen_tour: string }[];
};

export function buildRouteKeywordConflicts(rules: RouteRule[]): Map<string, RouteKeywordConflict["routes"]> {
  const map = new Map<string, RouteKeywordConflict["routes"]>();
  for (const r of rules) {
    for (const part of r.keywords.split(",")) {
      const kw = part.trim().toLowerCase();
      if (!kw) continue;
      const routes = map.get(kw) ?? [];
      if (!routes.some((x) => x.thi_truong === r.thi_truong && x.tuyen_tour === r.tuyen_tour)) {
        routes.push({ thi_truong: r.thi_truong, tuyen_tour: r.tuyen_tour });
      }
      map.set(kw, routes);
    }
  }
  return new Map([...map.entries()].filter(([, routes]) => routes.length > 1));
}

export function conflictHintForKeyword(
  kw: string,
  conflicts: Map<string, RouteKeywordConflict["routes"]>,
): string | null {
  const key = kw.trim().toLowerCase();
  if (!key) return null;
  const routes = conflicts.get(key);
  if (!routes || routes.length < 2) return null;
  return (
    `Từ «${key}» còn trong rule khác (${routes.map((r) => `${r.thi_truong}/${r.tuyen_tour}`).join("; ")}). `
    + "Mỗi dòng vẫn cần đủ tất cả từ sau dấu phẩy mới khớp."
  );
}
