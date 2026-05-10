import { useState } from "react";

const PALETTE = [
  "from-violet-500 to-fuchsia-500",
  "from-cyan-500 to-blue-500",
  "from-emerald-500 to-teal-500",
  "from-amber-500 to-orange-500",
  "from-rose-500 to-pink-500",
  "from-indigo-500 to-purple-500",
  "from-lime-500 to-green-500",
  "from-sky-500 to-cyan-500",
];

const SIZES = {
  sm: "h-8 w-8 text-xs",
  md: "h-12 w-12 text-sm",
  lg: "h-20 w-20 text-2xl",
} as const;

function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function paletteFor(name: string | null | undefined): string {
  if (!name) return PALETTE[0];
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) | 0;
  }
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

interface AvatarProps {
  name: string | null | undefined;
  photoUrl?: string | null;
  size?: keyof typeof SIZES;
  className?: string;
}

export function Avatar({ name, photoUrl, size = "md", className = "" }: AvatarProps) {
  const [imgFailed, setImgFailed] = useState(false);
  const sizeCls = SIZES[size];
  const useImage = photoUrl && !imgFailed;

  if (useImage) {
    return (
      <img
        src={photoUrl}
        alt={name ?? "Candidate"}
        onError={() => setImgFailed(true)}
        className={`${sizeCls} rounded-full object-cover bg-muted ${className}`}
      />
    );
  }

  return (
    <span
      aria-label={name ?? "Candidate"}
      className={`${sizeCls} rounded-full grid place-items-center font-semibold text-white bg-gradient-to-br ${paletteFor(name)} ${className}`}
    >
      {initials(name)}
    </span>
  );
}
