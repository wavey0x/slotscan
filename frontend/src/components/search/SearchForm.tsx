"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { CHAINS } from "@/lib/constants";
import { isAddress, isTxHash, saveRecentSearch } from "@/lib/utils";

export function SearchForm() {
  const router = useRouter();
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

    let url = `/${chain}/${address}`;

    if (txHash) {
      if (isTxHash(txHash)) {
        url += `?tx=${txHash}`;
      } else {
        setError("Invalid transaction hash format");
        return;
      }
    }

    saveRecentSearch({ chain, address, blockOrTx: txHash });
    router.push(url);
  };

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-xl space-y-4">
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

      <Input
        value={txHash}
        onChange={(e) => setTxHash(e.target.value)}
        placeholder="Transaction hash"
        className="font-mono"
      />

      {error && <p className="text-red text-sm">{error}</p>}

      <Button type="submit" variant="secondary" className="w-full">
        Analyze
      </Button>
    </form>
  );
}
