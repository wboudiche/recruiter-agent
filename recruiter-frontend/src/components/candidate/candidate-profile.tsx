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
  Phone,
  Twitter,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  const [editing, setEditing] = useState(false);
  const [photoUrl, setPhotoUrl] = useState(candidate.photo_url ?? "");
  const update = useUpdateCandidate(candidate.id);

  function save() {
    update.mutate(
      { photo_url: photoUrl.trim() || null },
      { onSuccess: () => setEditing(false) },
    );
  }

  function clearPhoto() {
    setPhotoUrl("");
    update.mutate(
      { photo_url: null },
      { onSuccess: () => setEditing(false) },
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
          onClick={() => setEditing(true)}
          aria-label="Edit photo"
          className="absolute -bottom-1 -right-1 grid h-7 w-7 place-items-center rounded-full bg-card border shadow-sm hover:bg-accent transition-colors"
        >
          <ImageIcon className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="flex-1 min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight truncate">
          {candidate.full_name ?? `Candidate #${candidate.id}`}
        </h1>
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
        {editing && (
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
                setEditing(false);
                setPhotoUrl(candidate.photo_url ?? "");
              }}
            >
              <X className="h-4 w-4" />
            </Button>
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
    <Card title="Skills">
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
    </Card>
  );
}

function ExperienceSection({ items }: { items: ExperienceItem[] }) {
  return (
    <Card title="Experience">
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
    </Card>
  );
}

function EducationSection({ items }: { items: EducationItem[] }) {
  return (
    <Card title="Education">
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
    </Card>
  );
}

function LinksSection({ items }: { items: LinkItem[] }) {
  return (
    <Card title="Links">
      <ul className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
        {items.map((l, i) => (
          <li key={i}>
            <a
              href={l.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 hover:text-primary transition-colors"
            >
              {iconForUrl(l.url)}
              {l.label || domainOf(l.url)}
              <ExternalLink className="h-3 w-3 opacity-50" />
            </a>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
        {title}
      </h3>
      {children}
    </div>
  );
}

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function iconForUrl(url: string) {
  const host = domainOf(url);
  const cls = "h-3.5 w-3.5";
  if (host.includes("linkedin.com")) return <Linkedin className={cls} />;
  if (host.includes("github.com")) return <Github className={cls} />;
  if (host.includes("twitter.com") || host.includes("x.com")) return <Twitter className={cls} />;
  return <Globe className={cls} />;
}
