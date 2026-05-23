import { useState } from "react";
import {
  ExternalLink,
  GraduationCap,
  Github,
  Globe,
  ImageIcon,
  Linkedin,
  Mail,
  MapPin,
  Pencil,
  Phone,
  Twitter,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card as UICard } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  CandidateRead,
  EducationItem,
  ExperienceItem,
  LinkItem,
  useUpdateCandidate,
} from "@/hooks/use-candidate";
import { Avatar } from "./avatar";

interface Props {
  candidate: CandidateRead;
}

export function CandidateProfile({ candidate }: Props) {
  return (
    <section className="space-y-5">
      <ProfileHeader candidate={candidate} />
      {candidate.summary && (
        <p className="text-sm text-muted-foreground leading-relaxed max-w-3xl">
          {candidate.summary}
        </p>
      )}
      {candidate.skills?.length > 0 && <SkillsSection skills={candidate.skills} />}
      {candidate.experience?.length > 0 && (
        <ExperienceSection items={candidate.experience} />
      )}
      {candidate.education?.length > 0 && (
        <EducationSection items={candidate.education} />
      )}
      {candidate.links?.length > 0 && <LinksSection items={candidate.links} />}
    </section>
  );
}

function ProfileHeader({ candidate }: { candidate: CandidateRead }) {
  const [editing, setEditing] = useState<"photo" | "identity" | null>(null);
  const [photoUrl, setPhotoUrl] = useState(candidate.photo_url ?? "");
  const [fullName, setFullName] = useState(candidate.full_name ?? "");
  const [email, setEmail] = useState(candidate.email ?? "");
  const [headline, setHeadline] = useState(candidate.headline ?? "");
  const [phone, setPhone] = useState(candidate.phone ?? "");
  const [location, setLocation] = useState(candidate.location ?? "");
  const [summary, setSummary] = useState(candidate.summary ?? "");
  const update = useUpdateCandidate(candidate.id);

  function startEditingPhoto() {
    setPhotoUrl(candidate.photo_url ?? "");
    setEditing("photo");
  }

  function startEditingIdentity() {
    setFullName(candidate.full_name ?? "");
    setEmail(candidate.email ?? "");
    setHeadline(candidate.headline ?? "");
    setPhone(candidate.phone ?? "");
    setLocation(candidate.location ?? "");
    setSummary(candidate.summary ?? "");
    setEditing("identity");
  }

  function save() {
    update.mutate(
      { photo_url: photoUrl.trim() || null },
      { onSuccess: () => setEditing(null) },
    );
  }

  function saveIdentity() {
    update.mutate(
      {
        full_name: fullName.trim() || null,
        email: email.trim() || null,
        headline: headline.trim() || null,
        phone: phone.trim() || null,
        location: location.trim() || null,
        summary: summary.trim() || null,
      },
      { onSuccess: () => setEditing(null) },
    );
  }

  function clearPhoto() {
    setPhotoUrl("");
    update.mutate(
      { photo_url: null },
      { onSuccess: () => setEditing(null) },
    );
  }

  return (
    <header className="flex items-start gap-5">
      <div className="relative shrink-0">
        <Avatar
          name={candidate.full_name}
          photoUrl={candidate.photo_url}
          size="lg"
        />
        <button
          type="button"
          onClick={startEditingPhoto}
          aria-label="Edit photo"
          className="absolute -bottom-1 -right-1 grid h-7 w-7 place-items-center rounded-full bg-card border shadow-sm hover:bg-accent transition-colors"
        >
          <ImageIcon className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start gap-2">
          <h1 className="text-2xl font-semibold tracking-tight truncate">
            {candidate.full_name ?? `Candidate #${candidate.id}`}
          </h1>
          <button
            type="button"
            onClick={startEditingIdentity}
            aria-label="Edit profile details"
            title="Edit name, email, phone, headline, location, summary"
            className="mt-1 grid h-6 w-6 place-items-center rounded-md border shadow-sm hover:bg-accent transition-colors shrink-0"
          >
            <Pencil className="h-3 w-3" />
          </button>
        </div>
        {candidate.headline && (
          <p className="text-base text-muted-foreground mt-0.5">{candidate.headline}</p>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-sm text-muted-foreground">
          {candidate.location && (
            <span className="inline-flex items-center gap-1">
              <MapPin className="h-3.5 w-3.5" />
              {candidate.location}
            </span>
          )}
          {candidate.email && (
            <a
              href={`mailto:${candidate.email}`}
              className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
            >
              <Mail className="h-3.5 w-3.5" />
              {candidate.email}
            </a>
          )}
          {candidate.phone && (
            <span className="inline-flex items-center gap-1">
              <Phone className="h-3.5 w-3.5" />
              {candidate.phone}
            </span>
          )}
        </div>
        {editing === "photo" && (
          <div className="mt-3 flex items-center gap-2 max-w-xl">
            <Input
              type="url"
              placeholder="https://example.com/photo.jpg"
              value={photoUrl}
              onChange={(e) => setPhotoUrl(e.target.value)}
              autoFocus
            />
            <Button size="sm" onClick={save} disabled={update.isPending}>
              Save
            </Button>
            {candidate.photo_url && (
              <Button
                size="sm"
                variant="outline"
                onClick={clearPhoto}
                disabled={update.isPending}
              >
                Remove
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(null);
                setPhotoUrl(candidate.photo_url ?? "");
              }}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        )}
        {editing === "identity" && (
          <div className="mt-3 grid gap-2 max-w-xl">
            <Input
              placeholder="Full name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              autoFocus
            />
            <div className="grid grid-cols-2 gap-2">
              <Input
                type="email"
                placeholder="email@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <Input
                placeholder="Phone"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />
            </div>
            <Input
              placeholder="Headline (e.g. Senior DevOps engineer)"
              value={headline}
              onChange={(e) => setHeadline(e.target.value)}
            />
            <Input
              placeholder="Location (e.g. Tunis, Tunisia)"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            />
            <Textarea
              placeholder="Summary — short professional bio"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              rows={4}
            />
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={saveIdentity} disabled={update.isPending}>
                Save
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(null)}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
    </header>
  );
}

function SkillsSection({ skills }: { skills: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? skills : skills.slice(0, 16);
  const hidden = skills.length - visible.length;

  return (
    <Section title="Skills">
      <div className="flex flex-wrap gap-1.5">
        {visible.map((s, i) => (
          <span
            key={`${s}-${i}`}
            className="px-2.5 py-1 rounded-md bg-accent/60 text-accent-foreground text-xs font-medium"
          >
            {s}
          </span>
        ))}
        {hidden > 0 && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="px-2.5 py-1 rounded-md text-xs text-muted-foreground hover:text-foreground"
          >
            + {hidden} more
          </button>
        )}
      </div>
    </Section>
  );
}

function ExperienceSection({ items }: { items: ExperienceItem[] }) {
  return (
    <Section title="Experience">
      <ol className="space-y-4">
        {items.map((it, i) => (
          <li key={i} className="relative pl-4 border-l-2 border-primary/30">
            <div className="font-medium">
              {it.title || "Role"}
              {it.company && (
                <span className="text-muted-foreground"> · {it.company}</span>
              )}
            </div>
            {(it.start || it.end) && (
              <div className="text-xs text-muted-foreground mt-0.5">
                {[it.start, it.end].filter(Boolean).join(" — ")}
              </div>
            )}
            {it.description && (
              <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed line-clamp-3">
                {it.description}
              </p>
            )}
          </li>
        ))}
      </ol>
    </Section>
  );
}

function EducationSection({ items }: { items: EducationItem[] }) {
  return (
    <Section title="Education">
      <ul className="space-y-2">
        {items.map((it, i) => (
          <li key={i} className="flex items-start gap-2 text-sm">
            <GraduationCap className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
            <div>
              <span className="font-medium">
                {[it.degree, it.field].filter(Boolean).join(" ") || "Degree"}
              </span>
              {it.school && (
                <span className="text-muted-foreground"> · {it.school}</span>
              )}
              {(it.start || it.end) && (
                <span className="text-muted-foreground">
                  {" · "}
                  {[it.start, it.end].filter(Boolean).join(" — ")}
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function LinksSection({ items }: { items: LinkItem[] }) {
  // Drop links that aren't plain http(s) — data:/javascript:/etc. could
  // execute or open uncontrolled origins when clicked.
  const safe = items.filter((l) => /^https?:\/\//i.test(l.url));
  if (safe.length === 0) return null;
  return (
    <Section title="Links">
      <ul className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
        {safe.map((l, i) => {
          const host = domainOf(l.url);
          return (
            <li key={i}>
              <a
                href={l.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 hover:text-primary transition-colors"
              >
                {iconForHost(host)}
                {l.label || host}
                <ExternalLink className="h-3 w-3 opacity-50" />
              </a>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <UICard className="p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
        {title}
      </h3>
      {children}
    </UICard>
  );
}

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function iconForHost(host: string) {
  const cls = "h-3.5 w-3.5";
  if (host.includes("linkedin.com")) return <Linkedin className={cls} />;
  if (host.includes("github.com")) return <Github className={cls} />;
  if (host.includes("twitter.com") || host.includes("x.com")) return <Twitter className={cls} />;
  return <Globe className={cls} />;
}
