"use client";

import { useEffect, useRef } from "react";
import { Phone, Scale, X } from "lucide-react";

import { HELPLINES, getAct, indiaCodeUrl } from "@/lib/legal-db";
import { Button } from "@/components/ui/primitives";

/**
 * Free legal aid and escalation.
 *
 * Uses the native <dialog> element, which gives focus trapping, Escape to close
 * and inert background content from the platform rather than from hand-written
 * key handlers that usually get one of those three wrong.
 */
export function DisclaimerModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const lsaa = getAct("LSAA");

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="aid-title"
      className="hc-border m-auto w-[min(92vw,42rem)] rounded-[var(--radius-card)] border border-[var(--line)] bg-[var(--surface)] p-0 text-[var(--ink)] backdrop:bg-navy-950/60"
    >
      <div className="flex items-start justify-between gap-4 border-b border-[var(--line)] p-5">
        <h2 id="aid-title" className="flex items-center gap-2 text-lg font-bold">
          <Scale className="size-5 text-saffron-600" aria-hidden="true" />
          Free legal aid and emergency contacts
        </h2>
        <Button variant="ghost" onClick={onClose} aria-label="Close" className="shrink-0 p-2">
          <X className="size-5" aria-hidden="true" />
        </Button>
      </div>

      <div className="space-y-5 p-5">
        <section aria-labelledby="eligibility">
          <h3 id="eligibility" className="mb-2 font-semibold">
            You may be entitled to a free lawyer
          </h3>
          <p className="text-sm text-[var(--ink-muted)]">
            Under Section 12 of the Legal Services Authorities Act 1987, legal services are free as
            of right for:
          </p>
          <ul className="mt-2 list-disc space-y-1 ps-5 text-sm text-[var(--ink-muted)]">
            <li>Women and children</li>
            <li>Members of a Scheduled Caste or Scheduled Tribe</li>
            <li>Victims of trafficking or of begar (forced labour)</li>
            <li>Persons with disabilities</li>
            <li>Victims of a mass disaster, ethnic violence, caste atrocity, flood or drought</li>
            <li>Industrial workmen</li>
            <li>Persons in custody, including protective homes and juvenile homes</li>
            <li>Anyone whose annual income is below the limit set by their State</li>
          </ul>
          {lsaa ? (
            <a
              href={indiaCodeUrl(lsaa)}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-block text-sm font-semibold text-saffron-ink underline underline-offset-2 dark:text-saffron-400"
            >
              Read the Act on India Code
              <span className="visually-hidden"> (opens in a new tab)</span>
            </a>
          ) : null}
        </section>

        <section aria-labelledby="how-to-apply">
          <h3 id="how-to-apply" className="mb-2 font-semibold">
            How to apply
          </h3>
          <ol className="list-decimal space-y-1 ps-5 text-sm text-[var(--ink-muted)]">
            <li>
              Call <a href="tel:15100" className="font-semibold underline">15100</a> — the NALSA
              helpline. It is free and available in many languages.
            </li>
            <li>
              Or go to your District Legal Services Authority, which sits in the district court
              complex. No appointment is needed.
            </li>
            <li>Carry any ID, and an income certificate if you are applying on income grounds.</li>
            <li>Ask for a Lok Adalat if your matter is a money claim — there is no court fee.</li>
          </ol>
        </section>

        <section aria-labelledby="helplines">
          <h3 id="helplines" className="mb-2 font-semibold">
            Helplines
          </h3>
          <ul className="grid gap-2 sm:grid-cols-2">
            {HELPLINES.map((helpline) => (
              <li key={helpline.number} className="hc-border rounded-lg border border-[var(--line)] p-2.5">
                <a href={`tel:${helpline.number}`} className="flex items-center gap-2 font-bold">
                  <Phone className="size-4 text-emerald-600" aria-hidden="true" />
                  {helpline.number}
                </a>
                <p className="mt-0.5 text-sm font-medium">{helpline.name}</p>
                <p className="text-xs text-[var(--ink-muted)]">{helpline.detail}</p>
              </li>
            ))}
          </ul>
        </section>

        <p className="border-t border-[var(--line)] pt-4 text-sm text-[var(--ink-muted)]">
          Adhikar provides AI-generated legal information for educational purposes only. It is not a
          substitute for professional legal advice. For formal representation, consult a registered
          Advocate.
        </p>
      </div>
    </dialog>
  );
}
