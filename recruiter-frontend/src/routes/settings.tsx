import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EnrichmentTab } from "@/components/settings/enrichment-tab";
import { LlmTab } from "@/components/settings/llm-tab";
import { NotificationsTab } from "@/components/settings/notifications-tab";
import { ProfileTab } from "@/components/settings/profile-tab";
import { SourcingTab } from "@/components/settings/sourcing-tab";
import { UsersTab } from "@/components/settings/users-tab";
import { useCurrentUser } from "@/hooks/use-current-user";

export default function Settings() {
  const me = useCurrentUser();

  // `me.data?.role === "admin"` is false both while the role is unknown
  // (query still loading) and once it resolves to a non-admin — those are
  // different situations. Rendering the tab set on the former would flash
  // the non-admin tabs for an admin (extra tabs popping in a moment
  // later); waiting for the role to be known avoids it, without changing
  // the eventual non-admin gating that the tests below cover.
  if (me.isLoading) {
    return (
      <div className="space-y-6">
        <h2 className="text-2xl font-semibold tracking-tight">Settings</h2>
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  const isAdmin = me.data?.role === "admin";

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold tracking-tight">Settings</h2>
      {/* `defaultValue` deliberately points at "profile" — the one tab
          every role can see. LLM/Notifications/Sourcing/Enrichment/Users
          only render for admins (see isAdmin below); defaulting to one of
          those would leave non-admins looking at a blank tab panel since
          none of their visible triggers would match it. */}
      <Tabs defaultValue="profile">
        <TabsList>
          {isAdmin && <TabsTrigger value="llm">LLM</TabsTrigger>}
          {isAdmin && <TabsTrigger value="notifications">Notifications</TabsTrigger>}
          {isAdmin && <TabsTrigger value="sourcing">Sourcing</TabsTrigger>}
          {isAdmin && <TabsTrigger value="enrichment">Enrichment</TabsTrigger>}
          <TabsTrigger value="profile">Profile</TabsTrigger>
          {isAdmin && <TabsTrigger value="users">Users</TabsTrigger>}
        </TabsList>
        {isAdmin && (
          <TabsContent value="llm" className="pt-6">
            <LlmTab />
          </TabsContent>
        )}
        {isAdmin && (
          <TabsContent value="notifications" className="pt-6">
            <NotificationsTab />
          </TabsContent>
        )}
        {isAdmin && (
          <TabsContent value="sourcing" className="pt-6">
            <SourcingTab />
          </TabsContent>
        )}
        {isAdmin && (
          <TabsContent value="enrichment" className="pt-6">
            <EnrichmentTab />
          </TabsContent>
        )}
        <TabsContent value="profile" className="pt-6">
          <ProfileTab />
        </TabsContent>
        {isAdmin && (
          <TabsContent value="users" className="pt-6">
            <UsersTab />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
