import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EnrichmentTab } from "@/components/settings/enrichment-tab";
import { LlmTab } from "@/components/settings/llm-tab";
import { NotificationsTab } from "@/components/settings/notifications-tab";
import { ProfileTab } from "@/components/settings/profile-tab";
import { SourcingTab } from "@/components/settings/sourcing-tab";

export default function Settings() {
  const [mode, setMode] = useState<"dark" | "light">("dark");
  return (
    <div className={`geist-theme ${mode === "dark" ? "dark" : ""} -mx-6 -my-4 px-6 py-6 min-h-[calc(100vh-4rem)]`}>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-semibold tracking-tight">Settings</h2>
        <button
          type="button"
          onClick={() => setMode(mode === "dark" ? "light" : "dark")}
          className="text-xs font-mono px-3 py-1.5 border border-[hsl(var(--border))] rounded-md hover:border-[hsl(var(--foreground))] transition-colors"
        >
          {mode === "dark" ? "◐ DARK" : "◑ LIGHT"}
        </button>
      </div>
      <Tabs defaultValue="llm">
        <TabsList>
          <TabsTrigger value="llm">LLM</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
          <TabsTrigger value="sourcing">Sourcing</TabsTrigger>
          <TabsTrigger value="enrichment">Enrichment</TabsTrigger>
          <TabsTrigger value="profile">Profile</TabsTrigger>
        </TabsList>
        <TabsContent value="llm" className="pt-6">
          <LlmTab />
        </TabsContent>
        <TabsContent value="notifications" className="pt-6">
          <NotificationsTab />
        </TabsContent>
        <TabsContent value="sourcing" className="pt-6">
          <SourcingTab />
        </TabsContent>
        <TabsContent value="enrichment" className="pt-6">
          <EnrichmentTab />
        </TabsContent>
        <TabsContent value="profile" className="pt-6">
          <ProfileTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
