import type { ReactNode } from "react";

const TOKEN_RE = /(```(?:[^`]|`(?!``))*```|`[^`\n]+`|\|\|[^\n]+?\|\||\*\*[^\n]+?\*\*|__[^\n]+?__|~~[^\n]+?~~|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|<a?:\w+:\d+>|\*[^*\n]+\*|_[^_\n]+_)/g;
const CUSTOM_EMOJI_RE = /^<(a)?:(\w+):(\d+)>$/;
const LINK_RE = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/;

function renderTokens(text: string, keyPrefix = "md"): ReactNode[] {
  return text.split(TOKEN_RE).filter(Boolean).map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    const emoji = part.match(CUSTOM_EMOJI_RE);
    if (emoji) {
      return (
        <img
          key={key}
          src={`https://cdn.discordapp.com/emojis/${emoji[3]}.${emoji[1] ? "gif" : "png"}`}
          alt={`:${emoji[2]}:`}
          className="inline-block h-5 w-5 align-text-bottom"
        />
      );
    }

    const link = part.match(LINK_RE);
    if (link) {
      return (
        <a key={key} href={link[2]} target="_blank" rel="noopener noreferrer" className="text-accent underline">
          {link[1]}
        </a>
      );
    }

    if (part.startsWith("```") && part.endsWith("```")) {
      const body = part.slice(3, -3).replace(/^[a-zA-Z0-9_+-]+\n/, "");
      return (
        <code key={key} className="my-1 block overflow-x-auto rounded bg-surface-3 px-2 py-1.5 font-mono text-[0.9em]">
          {body}
        </code>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={key} className="rounded bg-surface-3 px-1 font-mono text-[0.9em]">{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key}>{renderTokens(part.slice(2, -2), key)}</strong>;
    }
    if (part.startsWith("__") && part.endsWith("__")) {
      return <u key={key}>{renderTokens(part.slice(2, -2), key)}</u>;
    }
    if (part.startsWith("~~") && part.endsWith("~~")) {
      return <s key={key}>{renderTokens(part.slice(2, -2), key)}</s>;
    }
    if (part.startsWith("||") && part.endsWith("||")) {
      return (
        <span key={key} className="rounded bg-txt px-0.5 text-transparent transition-colors hover:bg-surface-3 hover:text-txt" title="Spoiler">
          {renderTokens(part.slice(2, -2), key)}
        </span>
      );
    }
    if ((part.startsWith("*") && part.endsWith("*")) || (part.startsWith("_") && part.endsWith("_"))) {
      return <em key={key}>{renderTokens(part.slice(1, -1), key)}</em>;
    }
    return <span key={key}>{part}</span>;
  });
}

export function DiscordMarkdown({ text }: { text: string }) {
  return <>{renderTokens(text)}</>;
}
