import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EnrichmentTab } from "@/components/settings/enrichment-tab";
import { LlmTab } from "@/components/settings/llm-tab";
import { NotificationsTab } from "@/components/settings/notifications-tab";
import { ProfileTab } from "@/components/settings/profile-tab";
import { SourcingTab } from "@/components/settings/sourcing-tab";

export default function Settings() {
  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Settings</h2>
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
