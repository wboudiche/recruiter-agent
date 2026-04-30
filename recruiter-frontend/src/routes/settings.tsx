import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LlmTab } from "@/components/settings/llm-tab";
import { NotificationsTab } from "@/components/settings/notifications-tab";
import { ProfileTab } from "@/components/settings/profile-tab";

export default function Settings() {
  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Settings</h2>
      <Tabs defaultValue="llm">
        <TabsList>
          <TabsTrigger value="llm">LLM</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
          <TabsTrigger value="profile">Profile</TabsTrigger>
        </TabsList>
        <TabsContent value="llm" className="pt-6">
          <LlmTab />
        </TabsContent>
        <TabsContent value="notifications" className="pt-6">
          <NotificationsTab />
        </TabsContent>
        <TabsContent value="profile" className="pt-6">
          <ProfileTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
