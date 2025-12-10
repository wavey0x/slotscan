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

    if (!isAddress(address)) {
      setError("Invalid contract address");
      return;
    }

    saveRecentSearch({ chain: "1", address });
    router.push(`/1/${address}`);
  };

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-xl space-y-4">
      <Input
        value={address}
        onChange={(e) => setAddress(e.target.value)}
        placeholder="Contract Address (0x...)"
        className="font-mono"
      />

      {error && <p className="text-red text-sm">{error}</p>}

      <Button type="submit" variant="secondary" className="w-full">
        View Storage
      </Button>
    </form>
  );
}
