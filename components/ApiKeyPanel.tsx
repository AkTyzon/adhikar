"use client";

import { useEffect, useState } from "react";
import { KeyRound, Check, Trash2 } from "lucide-react";

import { Badge, Button, Callout } from "@/components/ui/primitives";

/** Where the key lives in the browser. Never sent anywhere but our own API. */
export const KEY_STORAGE = "adhikar.gemini-key";

/**
 * Lets a visitor supply their own Gemini key.
 *
 * This is what makes a public deployment usable when the server holds no
 * credentials of its own: someone evaluating it pastes a key from Google AI
 * Studio and gets real answers immediately.
 *
 * The key is kept in this browser's localStorage and attached to API requests as
 * a header. It is never stored server-side, never logged, and never written into
 * a URL. That is stated on the panel, because asking someone for a credential
 * without saying where it goes is not a reasonable thing to do.
 */
export function ApiKeyPanel({ onChange }: { onChange: (key: string | null) => void }) {
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Read once on mount. Deferred by a tick rather than set synchronously inside
  // the effect, which React flags as causing a cascading render before first paint.
  useEffect(() => {
    let cancelled = false;
    const handle = setTimeout(() => {
      if (cancelled) return;
      try {
        // localStorage is unavailable in some privacy modes; a missing key is a
        // normal state, not an error worth showing.
        const existing = window.localStorage.getItem(KEY_STORAGE);
        if (existing) {
          setSaved(existing);
          onChange(existing);
        }
      } catch {
        /* ignore */
      }
    }, 0);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [onChange]);

  function save() {
    const key = value.trim();
    // Google issues keys in an "AIza…" form and a newer "AQ.…" form; both are
    // valid and an earlier check accepted only the first.
    const plausible =
      !/\s/.test(key) &&
      (/^AIza[0-9A-Za-z_-]{30,60}$/.test(key) || /^AQ\.[0-9A-Za-z_.-]{20,120}$/.test(key));
    if (!plausible) {
      setError("That does not look like a Google AI Studio key. They begin with “AIza” or “AQ.”.");
      return;
    }
    setError(null);
    try {
      window.localStorage.setItem(KEY_STORAGE, key);
    } catch {
      /* still usable for this session */
    }
    setSaved(key);
    setValue("");
    onChange(key);
  }

  function clear() {
    try {
      window.localStorage.removeItem(KEY_STORAGE);
    } catch {
      /* ignore */
    }
    setSaved(null);
    setValue("");
    setError(null);
    onChange(null);
  }

  return (
    <div className="hc-border rounded-lg border border-[var(--line)] bg-[var(--surface)] p-4">
      <h3 className="flex flex-wrap items-center gap-2 font-semibold">
        <KeyRound className="size-4 text-saffron-600" aria-hidden="true" />
        Use your own Gemini key
        {saved ? (
          <Badge tone="verified">
            <Check className="size-3.5" aria-hidden="true" />
            Active
          </Badge>
        ) : null}
      </h3>

      <p className="mt-1 text-sm text-[var(--ink-muted)]">
        Get a free key from{" "}
        <a
          href="https://aistudio.google.com/apikey"
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium underline underline-offset-2"
        >
          Google AI Studio
          <span className="visually-hidden"> (opens in a new tab)</span>
        </a>
        . It is kept in this browser only, sent to Adhikar&rsquo;s own server solely to
        forward your question to Google, and never stored or logged there.
      </p>

      {saved ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <code className="rounded bg-navy-100 px-2 py-1 font-mono text-xs dark:bg-navy-800">
            {/* Prefix and last four only, so the field can be recognised without
                the secret being readable over someone's shoulder. */}
            {saved.slice(0, 4)}…{saved.slice(-4)}
          </code>
          <Button variant="ghost" onClick={clear} className="px-2 py-1 text-xs">
            <Trash2 className="size-3.5" aria-hidden="true" />
            Remove
          </Button>
        </div>
      ) : (
        <form
          className="mt-3 flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <label htmlFor="gemini-key" className="visually-hidden">
            Your Google AI Studio API key
          </label>
          <input
            id="gemini-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="AIza…"
            aria-describedby={error ? "gemini-key-error" : undefined}
            aria-invalid={error ? true : undefined}
            className="hc-border min-w-0 flex-1 rounded-lg border border-[var(--line)] bg-[var(--surface)] px-3 py-2 font-mono text-sm"
          />
          <Button type="submit">Save key</Button>
        </form>
      )}

      {error ? (
        <div className="mt-2" id="gemini-key-error">
          <Callout tone="danger">{error}</Callout>
        </div>
      ) : null}
    </div>
  );
}
