"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { CHAINS } from "@/lib/constants";
import { isAddress, isTxHash, saveRecentSearch, cn } from "@/lib/utils";

type SearchMode = "transaction" | "layout";

export function SearchForm() {
  const router = useRouter();
  const [mode, setMode] = useState<SearchMode>("transaction");
  const [chain, setChain] = useState("1");
  const [address, setAddress] = useState("");
  const [txHash, setTxHash] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!isAddress(address)) {
      setError("Invalid contract address");
      return;
    }

    if (mode === "transaction") {
      if (!txHash) {
        // Go to contract page without tx hash
        saveRecentSearch({ chain, address, blockOrTx: "" });
        router.push(`/${chain}/${address}`);
        return;
      }

      if (!isTxHash(txHash)) {
        setError("Invalid transaction hash format");
        return;
      }

      saveRecentSearch({ chain, address, blockOrTx: txHash });
      router.push(`/${chain}/${address}?tx=${txHash}`);
    } else {
      // Layout mode - go directly to layout page
      saveRecentSearch({ chain, address, blockOrTx: "" });
      router.push(`/${chain}/${address}/layout`);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-xl space-y-4">
      {/* Mode toggle */}
      <div className="flex justify-center gap-1 mb-2">
        <button
          type="button"
          onClick={() => setMode("transaction")}
          className={cn(
            "px-4 py-1.5 text-sm transition-colors",
            mode === "transaction"
              ? "text-gray-900 border-b-2 border-black"
              : "text-gray-500 hover:text-gray-700 border-b-2 border-transparent"
          )}
        >
          Transaction
        </button>
        <button
          type="button"
          onClick={() => setMode("layout")}
          className={cn(
            "px-4 py-1.5 text-sm transition-colors",
            mode === "layout"
              ? "text-gray-900 border-b-2 border-black"
              : "text-gray-500 hover:text-gray-700 border-b-2 border-transparent"
          )}
        >
          Layout
        </button>
      </div>

      {/* Chain and address */}
      <div className="flex gap-2">
        <Select
          value={chain}
          onChange={setChain}
          options={CHAINS}
          className="w-40"
        />
        <Input
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="Contract Address (0x...)"
          className="flex-1 font-mono"
        />
      </div>

      {/* Transaction hash - only in transaction mode */}
      {mode === "transaction" && (
        <Input
          value={txHash}
          onChange={(e) => setTxHash(e.target.value)}
          placeholder="Transaction hash (optional)"
          className="font-mono"
        />
      )}

      {error && <p className="text-red text-sm">{error}</p>}

      <Button type="submit" variant="secondary" className="w-full">
        {mode === "transaction" ? "Analyze Transaction" : "View Layout"}
      </Button>
    </form>
  );
}
