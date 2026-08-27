"use client";

import { useLiveStream } from "@/lib/hooks/useLiveStream";
import { MarketEmbed } from "@/components/MarketEmbed";
import { StrategyBoard } from "@/components/StrategyBoard";
import { CopyTradingPanel } from "@/components/CopyTradingPanel";

export default function BoardPage() {
  const { data, connected } = useLiveStream();

  return (
    <>
      <p className="page-title">Board — Polymarket BTC 5-min Up/Down</p>
      <MarketEmbed
        snapshot={data?.snapshot ?? null}
        history={data?.history ?? []}
        connected={connected}
        mode="live"
      />
      <StrategyBoard signals={data?.signals ?? []} />
      {data?.copy && <CopyTradingPanel copy={data.copy} strategies={data.signals} />}
    </>
  );
}
