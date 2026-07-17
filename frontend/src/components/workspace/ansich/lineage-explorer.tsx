"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchAnsichContentExposures,
  fetchAnsichContentLineage,
  fetchAnsichContextCompression,
} from "@/core/ansich/api";
import type {
  AnsichContentLineage,
  AnsichContextCompression,
  AnsichLineageNode,
  AnsichPossibleExposures,
} from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

type TraceResult = AnsichContentLineage | AnsichPossibleExposures;

export function AnsichBlockLineageExplorer({ blockId }: { blockId: string }) {
  const { t } = useI18n();
  const [result, setResult] = useState<TraceResult | null>(null);
  const [loading, setLoading] = useState<
    "backward" | "forward" | "exposures" | null
  >(null);
  const [error, setError] = useState<string | null>(null);

  async function load(kind: "backward" | "forward" | "exposures") {
    setLoading(kind);
    setError(null);
    try {
      if (kind === "exposures") {
        setResult((await fetchAnsichContentExposures(blockId)).exposures);
      } else {
        setResult((await fetchAnsichContentLineage(blockId, kind)).lineage);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t.ansich.loadFailed);
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="space-y-3 border-t pt-3">
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={loading !== null}
          onClick={() => load("backward")}
        >
          {loading === "backward"
            ? t.ansich.loading
            : t.ansich.loadBackwardLineage}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={loading !== null}
          onClick={() => load("forward")}
        >
          {loading === "forward"
            ? t.ansich.loading
            : t.ansich.loadForwardLineage}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={loading !== null}
          onClick={() => load("exposures")}
        >
          {loading === "exposures"
            ? t.ansich.loading
            : t.ansich.loadPossibleExposures}
        </Button>
      </div>
      {error && <div className="text-destructive text-xs">{error}</div>}
      {result && <LineageResult result={result} />}
    </div>
  );
}

function LineageResult({ result }: { result: TraceResult }) {
  const { t } = useI18n();
  const exposures = result.semantic === "possible_exposure" ? result : null;
  return (
    <section className="bg-muted/30 space-y-3 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium">{t.ansich.lineage}</div>
        <Badge variant="secondary">{result.semantic}</Badge>
      </div>
      <p className="text-muted-foreground text-xs">
        {exposures
          ? t.ansich.possibleExposureSemantic
          : t.ansich.provenanceSemantic}
      </p>
      {result.truncated && (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-800 dark:text-amber-300">
          {t.ansich.lineageTruncated} ({result.truncation_reason})
        </div>
      )}
      <div aria-label={t.ansich.graphView} className="space-y-2">
        <div className="text-muted-foreground text-xs font-medium uppercase">
          {t.ansich.graphView}
        </div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {result.nodes.map((node) => (
            <LineageNode key={node.block_id} node={node} />
          ))}
        </div>
        {result.edges.length > 0 && (
          <div className="space-y-1 font-mono text-xs">
            {result.edges.map((edge) => (
              <div
                key={`${edge.derived_block_id}:${edge.source_block_id}:${edge.transform_kind}`}
                className="text-muted-foreground rounded border border-dashed px-2 py-1"
              >
                {shortId(edge.derived_block_id)} → {shortId(edge.source_block_id)} ·{" "}
                {edge.transform_kind}
              </div>
            ))}
          </div>
        )}
      </div>
      {result.unknown_gaps.length > 0 && (
        <div className="space-y-1 text-xs">
          <div className="font-medium">{t.ansich.unknownGaps}</div>
          {result.unknown_gaps.map((gap) => (
            <code key={gap.block_id} className="block break-all">
              {gap.block_id} · {gap.reason}
            </code>
          ))}
        </div>
      )}
      {exposures && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="p-2">{t.ansich.step}</th>
                <th className="p-2">{t.ansich.block}</th>
                <th className="p-2">{t.ansich.snapshotOrdinal}</th>
                <th className="p-2">{t.ansich.ordering}</th>
              </tr>
            </thead>
            <tbody>
              {exposures.items.map((item) => (
                <tr
                  key={`${item.snapshot_id}:${item.snapshot_ordinal}:${item.descendant_block_id}`}
                  className="border-t"
                >
                  <td className="p-2">#{item.step_seq}</td>
                  <td className="p-2 font-mono" title={item.descendant_block_id}>
                    {shortId(item.descendant_block_id)}
                  </td>
                  <td className="p-2">#{item.snapshot_ordinal}</td>
                  <td className="p-2">
                    <Badge variant="outline">{item.ordering}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details>
        <summary className="cursor-pointer text-xs font-medium">
          {t.ansich.tableView}
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="p-2">{t.ansich.depth}</th>
                <th className="p-2">{t.ansich.block}</th>
                <th className="p-2">Kind</th>
                <th className="p-2">{t.ansich.producer}</th>
                <th className="p-2">Size</th>
              </tr>
            </thead>
            <tbody>
              {result.nodes.map((node) => (
                <tr key={node.block_id} className="border-t">
                  <td className="p-2">{node.depth}</td>
                  <td className="p-2 font-mono break-all">{node.block_id}</td>
                  <td className="p-2">{node.kind}</td>
                  <td className="p-2">{node.producer?.producer_kind ?? "—"}</td>
                  <td className="p-2">
                    {node.token_estimate} {t.ansich.tokens} · {node.byte_size} bytes
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function LineageNode({ node }: { node: AnsichLineageNode }) {
  const { t } = useI18n();
  return (
    <div className="bg-background space-y-1 rounded border p-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <Badge variant="outline">
          {t.ansich.depth} {node.depth}
        </Badge>
        {node.payload_status === "missing" && (
          <Badge variant="outline">{t.ansich.missingBlocks}</Badge>
        )}
      </div>
      <div className="font-medium">{node.kind}</div>
      <code className="text-muted-foreground block truncate" title={node.block_id}>
        {node.block_id}
      </code>
      <div className="text-muted-foreground">
        {node.producer?.producer_kind ?? "—"} · {node.token_estimate}{" "}
        {t.ansich.tokens} · {node.byte_size} bytes
      </div>
    </div>
  );
}

export function AnsichCompressionExplorer({
  compressionIds,
}: {
  compressionIds: string[];
}) {
  const { t } = useI18n();
  const [compression, setCompression] =
    useState<AnsichContextCompression | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load(compressionId: string) {
    setLoadingId(compressionId);
    setError(null);
    try {
      setCompression(
        (await fetchAnsichContextCompression(compressionId)).compression,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t.ansich.loadFailed);
    } finally {
      setLoadingId(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t.ansich.compressions}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {compressionIds.length === 0 ? (
          <div className="text-muted-foreground text-sm">
            {t.ansich.noCompressions}
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {compressionIds.map((compressionId, index) => (
              <Button
                key={compressionId}
                size="sm"
                variant={
                  compression?.compression_id === compressionId
                    ? "default"
                    : "outline"
                }
                disabled={loadingId !== null}
                onClick={() => load(compressionId)}
              >
                {loadingId === compressionId
                  ? t.ansich.loading
                  : `${t.ansich.loadCompression} #${index + 1}`}
              </Button>
            ))}
          </div>
        )}
        {error && <div className="text-destructive text-xs">{error}</div>}
        {compression && <CompressionDetail compression={compression} />}
      </CardContent>
    </Card>
  );
}

function CompressionDetail({
  compression,
}: {
  compression: AnsichContextCompression;
}) {
  const { t } = useI18n();
  return (
    <div className="space-y-3 rounded-md border p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <code className="text-xs break-all">{compression.compression_id}</code>
        <Badge variant="secondary">{compression.status}</Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <Metric
          label={t.ansich.beforeAfter}
          value={`${compression.before_tokens} → ${compression.after_tokens} ${t.ansich.tokens}`}
        />
        <Metric
          label={t.ansich.algorithm}
          value={`${compression.algorithm}@${compression.algorithm_version}`}
        />
        <Metric
          label={t.ansich.summaryBlock}
          value={shortId(compression.summary_block.block_id)}
        />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="p-2">{t.ansich.disposition}</th>
              <th className="p-2">#</th>
              <th className="p-2">{t.ansich.block}</th>
              <th className="p-2">Kind</th>
              <th className="p-2">Size</th>
            </tr>
          </thead>
          <tbody>
            {compression.items.map((item) => (
              <tr
                key={`${item.disposition}:${item.ordinal}:${item.block.block_id}`}
                className="border-t"
              >
                <td className="p-2">
                  <Badge variant="outline">{item.disposition}</Badge>
                </td>
                <td className="p-2">{item.ordinal}</td>
                <td className="p-2 font-mono" title={item.block.block_id}>
                  {shortId(item.block.block_id)}
                </td>
                <td className="p-2">{item.block.kind}</td>
                <td className="p-2">
                  {item.block.token_estimate} {t.ansich.tokens} ·{" "}
                  {item.block.byte_size} bytes
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <AnsichBlockLineageExplorer
        blockId={compression.summary_block.block_id}
      />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-muted/40 rounded p-2">
      <div className="text-muted-foreground text-xs">{label}</div>
      <div className="mt-1 font-mono text-xs break-all">{value}</div>
    </div>
  );
}

function shortId(value: string): string {
  return value.length <= 12 ? value : `${value.slice(0, 8)}…${value.slice(-4)}`;
}
