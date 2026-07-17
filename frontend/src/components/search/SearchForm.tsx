"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { inspectionPath } from "@/lib/navigation";

export function SearchForm() {
  const router = useRouter();
  const [address, setAddress] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    const value = address.trim();
    const destination = inspectionPath(value);
    if (!destination) {
      setError("Enter a contract address or transaction hash");
      return;
    }
    router.push(destination);
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
