import { describe, expect, it, rs } from "@rstest/core";

import {
  buildAnsichHealthDismissalKey,
  clearAnsichHealthDismissal,
  readAnsichHealthDismissal,
  subscribeAnsichHealthDismissals,
  writeAnsichHealthDismissal,
  type AnsichHealthDismissalStorage,
} from "@/core/ansich/health-dismissal";
import { ANSICH_HEALTH_STATUSES } from "@/core/ansich/types";

class MemoryStorage implements AnsichHealthDismissalStorage {
  readonly values = new Map<string, string>();
  throwOnRead = false;
  throwOnWrite = false;

  getItem(key: string) {
    if (this.throwOnRead) {
      throw new DOMException("Storage is unavailable");
    }
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    if (this.throwOnWrite) {
      throw new DOMException("Storage quota exceeded");
    }
    this.values.set(key, value);
  }

  removeItem(key: string) {
    if (this.throwOnWrite) {
      throw new DOMException("Storage is unavailable");
    }
    this.values.delete(key);
  }
}

const snapshot = {
  failedJobs: 2,
  lostObservations: 1,
  status: "degraded" as const,
};

describe("Ansich health dismissal keys", () => {
  it("keeps the system scope and each Task scope independent", () => {
    const system = buildAnsichHealthDismissalKey(undefined);
    const taskOne = buildAnsichHealthDismissalKey("task-1");
    const taskTwo = buildAnsichHealthDismissalKey("task-2");

    expect(new Set([system, taskOne, taskTwo]).size).toBe(3);
    expect(system).toContain("ansich");
    expect(taskOne).toContain("task-1");
  });

  it("encodes a Task id that would otherwise split the key", () => {
    expect(buildAnsichHealthDismissalKey("a:b")).toContain("a%3Ab");
  });
});

describe("Ansich health dismissal storage", () => {
  it("round-trips the dismissed state snapshot", () => {
    const storage = new MemoryStorage();
    const key = buildAnsichHealthDismissalKey("task-1");

    writeAnsichHealthDismissal(storage, key, snapshot);

    expect(readAnsichHealthDismissal(storage, key)).toEqual(snapshot);
  });

  it("clears a record", () => {
    const storage = new MemoryStorage();
    const key = buildAnsichHealthDismissalKey("task-1");
    writeAnsichHealthDismissal(storage, key, snapshot);

    clearAnsichHealthDismissal(storage, key);

    expect(readAnsichHealthDismissal(storage, key)).toBeNull();
  });

  it("round-trips an unknown failure count without inventing a zero", () => {
    const storage = new MemoryStorage();
    const key = buildAnsichHealthDismissalKey("task-1");

    writeAnsichHealthDismissal(storage, key, { ...snapshot, failedJobs: null });

    expect(readAnsichHealthDismissal(storage, key)).toEqual({
      ...snapshot,
      failedJobs: null,
    });
  });

  it("round-trips a dismissal taken at any collector status", () => {
    // A record dismissed while the collector was `recovering` used to fail
    // validation and re-promote its banner on the next poll — the validator
    // still knew only the four statuses that existed before the lifecycle
    // states landed.
    const storage = new MemoryStorage();
    const key = buildAnsichHealthDismissalKey("task-1");

    for (const status of ANSICH_HEALTH_STATUSES) {
      writeAnsichHealthDismissal(storage, key, { ...snapshot, status });

      expect(readAnsichHealthDismissal(storage, key)).toEqual({
        ...snapshot,
        status,
      });
    }
  });

  it("treats a malformed or foreign record as no dismissal", () => {
    const storage = new MemoryStorage();
    const key = buildAnsichHealthDismissalKey("task-1");

    storage.values.set(key, "not json");
    expect(readAnsichHealthDismissal(storage, key)).toBeNull();

    storage.values.set(key, JSON.stringify({ version: 999, ...snapshot }));
    expect(readAnsichHealthDismissal(storage, key)).toBeNull();

    storage.values.set(
      key,
      JSON.stringify({ version: 1, failedJobs: "two", lostObservations: 1 }),
    );
    expect(readAnsichHealthDismissal(storage, key)).toBeNull();

    storage.values.set(
      key,
      JSON.stringify({ version: 1, ...snapshot, status: "reticulating" }),
    );
    expect(readAnsichHealthDismissal(storage, key)).toBeNull();
  });

  it("never throws when storage is unavailable", () => {
    const storage = new MemoryStorage();
    const key = buildAnsichHealthDismissalKey(undefined);
    storage.throwOnRead = true;
    storage.throwOnWrite = true;

    expect(() =>
      writeAnsichHealthDismissal(storage, key, snapshot),
    ).not.toThrow();
    expect(() => clearAnsichHealthDismissal(storage, key)).not.toThrow();
    expect(readAnsichHealthDismissal(storage, key)).toBeNull();
    expect(readAnsichHealthDismissal(null, key)).toBeNull();
  });
});

describe("Ansich health dismissal subscribers", () => {
  it("notifies every mounted health line so instances stay in sync", () => {
    const storage = new MemoryStorage();
    const key = buildAnsichHealthDismissalKey("task-1");
    const listener = rs.fn();
    const unsubscribe = subscribeAnsichHealthDismissals(listener);

    writeAnsichHealthDismissal(storage, key, snapshot);
    clearAnsichHealthDismissal(storage, key);
    expect(listener.mock.calls.length).toBe(2);

    unsubscribe();
    writeAnsichHealthDismissal(storage, key, snapshot);
    expect(listener.mock.calls.length).toBe(2);
  });
});
