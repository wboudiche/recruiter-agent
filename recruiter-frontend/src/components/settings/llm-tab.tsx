import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  SecretField,
  secretToPayload,
  UNCHANGED,
  type SecretValue,
} from "./secret-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

const ANTHROPIC_MODEL_DEFAULT = "claude-sonnet-4-6";
const LOCAL_MODEL_DEFAULT = "gpt-oss-120b";

const ANTHROPIC_MODELS = [
  "claude-opus-4-7",
  "claude-sonnet-4-6",
  "claude-haiku-4-5-20251001",
];

export function LlmTab() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const [provider, setProvider] = useState<string | undefined>();
  const [anthropicKey, setAnthropicKey] = useState<SecretValue>(UNCHANGED);
  const [anthropicModel, setAnthropicModel] = useState<string | undefined>();
  const [localUrl, setLocalUrl] = useState<string | undefined>();
  const [localKey, setLocalKey] = useState<SecretValue>(UNCHANGED);
  const [localModel, setLocalModel] = useState<string | undefined>();

  if (settings.isLoading) return <p>Loading…</p>;
  if (!settings.data) return <p>No settings.</p>;

  const current = settings.data;
  const effProvider = provider ?? current.default_llm_provider;
  const effLocalUrl = localUrl ?? current.local_llm_url ?? "";
  const currentOverrides = (current.model_overrides ?? {}) as Record<string, string>;
  const effAnthropicModel =
    anthropicModel ?? currentOverrides.anthropic_model ?? ANTHROPIC_MODEL_DEFAULT;
  const effLocalModel =
    localModel ?? currentOverrides.local_model ?? LOCAL_MODEL_DEFAULT;

  function save() {
    const body: Record<string, unknown> = {};
    if (provider !== undefined && provider !== current.default_llm_provider)
      body.default_llm_provider = provider;
    const anthropicPayload = secretToPayload(anthropicKey);
    if (anthropicPayload !== undefined) body.anthropic_api_key = anthropicPayload;
    if (
      localUrl !== undefined &&
      localUrl !== (current.local_llm_url ?? "")
    )
      body.local_llm_url = localUrl;
    const localKeyPayload = secretToPayload(localKey);
    if (localKeyPayload !== undefined) body.local_llm_api_key = localKeyPayload;

    const nextOverrides: Record<string, string> = { ...currentOverrides };
    let overridesDirty = false;
    if (anthropicModel !== undefined && anthropicModel !== (currentOverrides.anthropic_model ?? "")) {
      if (anthropicModel) nextOverrides.anthropic_model = anthropicModel;
      else delete nextOverrides.anthropic_model;
      overridesDirty = true;
    }
    if (localModel !== undefined && localModel !== (currentOverrides.local_model ?? "")) {
      if (localModel) nextOverrides.local_model = localModel;
      else delete nextOverrides.local_model;
      overridesDirty = true;
    }
    if (overridesDirty) body.model_overrides = nextOverrides;

    update.mutate(body, {
      onSuccess: () => {
        setAnthropicKey(UNCHANGED);
        setLocalKey(UNCHANGED);
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
        <>
          <SecretField
            id="llm-anthropic-key"
            label="Anthropic API key"
            isSet={current.has_anthropic_api_key}
            value={anthropicKey}
            onChange={setAnthropicKey}
            unsetPlaceholder="sk-ant-…"
          />
          <div className="space-y-2">
            <Label>Model</Label>
            <Input
              list="anthropic-models"
              placeholder={ANTHROPIC_MODEL_DEFAULT}
              value={effAnthropicModel}
              onChange={(e) => setAnthropicModel(e.target.value)}
            />
            <datalist id="anthropic-models">
              {ANTHROPIC_MODELS.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
            <p className="text-xs text-muted-foreground">
              Supported: <code>claude-opus-4-7</code>,{" "}
              <code>claude-sonnet-4-6</code>,{" "}
              <code>claude-haiku-4-5-20251001</code>. Default if blank:{" "}
              <code>{ANTHROPIC_MODEL_DEFAULT}</code>.
            </p>
          </div>
        </>
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
          <SecretField
            id="llm-local-key"
            label="Local LLM API key (optional)"
            isSet={current.has_local_llm_api_key}
            value={localKey}
            onChange={setLocalKey}
            unsetPlaceholder="leave blank for unauthenticated local servers"
            help="Required for hosted endpoints like ai.linagora.com or OpenRouter. Skip for true-local Ollama / vLLM."
          />
          <div className="space-y-2">
            <Label>Model</Label>
            <Input
              placeholder={LOCAL_MODEL_DEFAULT}
              value={effLocalModel}
              onChange={(e) => setLocalModel(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              The exact model id depends on the gateway behind the URL above.
              Common values:
            </p>
            <ul className="text-xs text-muted-foreground list-disc pl-5 space-y-0.5">
              <li>
                <b>ai.linagora.com</b>: <code>gpt-oss-120b</code>,{" "}
                <code>gpt-oss-20b</code> (check with your LINAGORA admin for the
                full catalog).
              </li>
              <li>
                <b>OpenRouter</b>: <code>openai/gpt-4o</code>,{" "}
                <code>anthropic/claude-3-5-sonnet</code>,{" "}
                <code>meta-llama/llama-3.1-70b-instruct</code> (provider-prefixed,
                <code>:free</code> tier slugs are deprecated on most gateways).
              </li>
              <li>
                <b>Ollama / vLLM (local)</b>: whatever model id you loaded —
                e.g. <code>llama3</code>, <code>mistral</code>,{" "}
                <code>qwen2.5-coder</code>.
              </li>
            </ul>
            <p className="text-xs text-muted-foreground">
              Default if blank: <code>{LOCAL_MODEL_DEFAULT}</code>.
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
