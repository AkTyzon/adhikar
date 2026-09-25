import { PhoneCall } from "lucide-react";

import { HELPLINES } from "@/lib/legal-db";

/**
 * Always-visible emergency numbers.
 *
 * Placed directly under the header rather than in the footer. Someone arriving
 * because they are being hurt right now should not have to scroll past an
 * explanation of the product to find 112.
 */
export function EmergencyBar() {
  const primary = HELPLINES.filter((helpline) => helpline.primary);

  return (
    <div className="border-b border-[var(--line)] bg-danger-100 dark:bg-danger-700/20">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
        <p className="flex items-center gap-1.5 text-xs font-bold text-danger-700 dark:text-danger-100">
          <PhoneCall className="size-3.5" aria-hidden="true" />
          In danger right now?
        </p>
        <ul className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          {primary.map((helpline) => (
            <li key={helpline.number}>
              <a
                href={`tel:${helpline.number}`}
                className="text-xs font-semibold text-danger-700 underline underline-offset-2 dark:text-danger-100"
                title={helpline.detail}
              >
                {helpline.number}
                <span className="ms-1 font-normal">{helpline.name}</span>
              </a>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
