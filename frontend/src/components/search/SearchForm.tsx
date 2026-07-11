"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { isAddress, saveRecentSearch } from "@/lib/utils";

export function SearchForm() {
  const router = useRouter();
  const [address, setAddress] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    const value = address.trim();
    if (/^0x[a-fA-F0-9]{64}$/.test(value)) {
      router.push(`/1/tx/${value}`);
      return;
    }

    if (!isAddress(value)) {
      setError("Enter a contract address or transaction hash");
      return;
    }

    saveRecentSearch({ chain: "1", address: value });
    router.push(`/1/${value}`);
  };

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-xl space-y-4">
      <Input
        value={address}
        onChange={(e) => setAddress(e.target.value)}
        placeholder="Contract address or transaction hash (0x...)"
        className="font-mono"
      />

      {error && <p className="text-red text-sm">{error}</p>}

      <Button type="submit" variant="secondary" className="w-full">
        Analyze Storage
      </Button>
    </form>
  );
}
