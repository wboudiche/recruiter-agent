import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

export function LlmTab() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const [provider, setProvider] = useState<string | undefined>();
  const [anthropicKey, setAnthropicKey] = useState("");
  const [localUrl, setLocalUrl] = useState<string | undefined>();
  const [localKey, setLocalKey] = useState("");

  if (settings.isLoading) return <p>Loading…</p>;
  if (!settings.data) return <p>No settings.</p>;

  const current = settings.data;
  const effProvider = provider ?? current.default_llm_provider;
  const effLocalUrl = localUrl ?? current.local_llm_url ?? "";

  function save() {
    const body: Record<string, unknown> = {};
    if (provider !== undefined && provider !== current.default_llm_provider)
      body.default_llm_provider = provider;
    if (anthropicKey) body.anthropic_api_key = anthropicKey;
    if (
      localUrl !== undefined &&
      localUrl !== (current.local_llm_url ?? "")
    )
      body.local_llm_url = localUrl;
    if (localKey) body.local_llm_api_key = localKey;
    update.mutate(body, {
      onSuccess: () => {
        setAnthropicKey("");
        setLocalKey("");
      },
    });
  }

  return (
    <div className="space-y-4 max-w-md">
      <div className="space-y-2">
        <Label>Provider</Label>
        <Select value={effProvider} onValueChange={setProvider}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="anthropic">Anthropic</SelectItem>
            <SelectItem value="local">Local (Ollama / vLLM)</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {effProvider === "anthropic" && (
        <div className="space-y-2">
          <Label>Anthropic API key</Label>
          <Input
            type="password"
            placeholder={
              current.has_anthropic_api_key ? "•••••• (set)" : "sk-ant-…"
            }
            value={anthropicKey}
            onChange={(e) => setAnthropicKey(e.target.value)}
          />
        </div>
      )}

      {effProvider === "local" && (
        <>
          <div className="space-y-2">
            <Label>Local LLM URL</Label>
            <Input
              placeholder="http://localhost:11434/v1"
              value={effLocalUrl}
              onChange={(e) => setLocalUrl(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>Local LLM API key (optional)</Label>
            <Input
              type="password"
              placeholder={
                current.has_local_llm_api_key
                  ? "•••••• (set)"
                  : "leave blank for unauthenticated local servers"
              }
              value={localKey}
              onChange={(e) => setLocalKey(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Required for hosted endpoints like ai.linagora.com or OpenRouter.
              Skip for true-local Ollama / vLLM.
            </p>
          </div>
        </>
      )}

      <Button onClick={save} disabled={update.isPending}>
        {update.isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}
