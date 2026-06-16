import { useState, useCallback } from "react";
import { ingestTicket } from "../../../api/client";
import type { Category, IngestResponse } from "../../../types";

interface FormState {
  title: string;
  description: string;
  priority: number;
  category: Category | "";
}

export function useIngestTicket() {
  const [form, setForm] = useState<FormState>({
    title: "",
    description: "",
    priority: 3,
    category: "",
  });
  const [result, setResult] = useState<IngestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async () => {
    setError(null);
    setLoading(true);
    setResult(null);
    try {
      const res = await ingestTicket({
        title: form.title,
        description: form.description,
        priority: form.priority,
        category: form.category || undefined,
      });
      setResult(res);
      setForm({ title: "", description: "", priority: 3, category: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed.");
    } finally {
      setLoading(false);
    }
  }, [form]);

  return { form, setForm, result, loading, error, submit };
}
