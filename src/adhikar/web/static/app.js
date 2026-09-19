/* Progressive enhancement only.
 *
 * Every action on this site works without JavaScript: forms POST and the server
 * renders the result. This file improves three things and does nothing else.
 *
 *   1. Focus management. After a full-page form round trip, focus lands back at
 *      the top of the document and a keyboard user has to re-navigate to where
 *      they were. Moving focus to the answer or the error summary is the single
 *      biggest usability difference for keyboard and screen-reader users.
 *   2. Submission feedback, announced through a live region rather than only
 *      shown as a spinner.
 *   3. Cross-linking evidence highlights to the findings that produced them.
 *
 * No inline script anywhere, so the Content-Security-Policy needs no
 * 'unsafe-inline' and a bug in document escaping cannot become script execution.
 */

(function () {
  "use strict";

  /** Move focus to an element, making it programmatically focusable if needed. */
  function focusElement(element) {
    if (!element) return;
    if (!element.hasAttribute("tabindex")) {
      element.setAttribute("tabindex", "-1");
    }
    element.focus({ preventScroll: false });
  }

  /* ------------------------------------------------------ error recovery */
  // An error summary rendered by the server should receive focus immediately,
  // so the problem is announced rather than silently present above the fold.
  const errorSummary = document.getElementById("error-summary");
  if (errorSummary) {
    focusElement(errorSummary);
  }

  /* --------------------------------------------------- answer focus move */
  // After asking a question the page re-renders. Put the user back at the
  // answer rather than at the top of a long report.
  const answerHeading = document.getElementById("answer-heading");
  if (answerHeading && window.location.hash === "") {
    focusElement(answerHeading);
  }

  /* ------------------------------------------------- submission feedback */
  document.querySelectorAll("form").forEach(function (form) {
    form.addEventListener("submit", function () {
      const button = form.querySelector('button[type="submit"]');
      const status = form.querySelector("[data-upload-status]");

      if (button) {
        // aria-disabled rather than disabled: a genuinely disabled control is
        // removed from the accessibility tree and stops announcing itself.
        button.setAttribute("aria-disabled", "true");
        button.dataset.originalText = button.textContent;
        button.textContent = "Working…";
      }
      if (status) {
        status.textContent =
          "Analysing your document. Large files may take a few seconds.";
      }
    });
  });

  /* ------------------------------------------- evidence cross-navigation */
  // Clicking a finding's evidence scrolls the full document view to the same
  // passage, so the reader can see the clause in its surrounding context.
  const documentView = document.querySelector(".document-text");
  if (documentView) {
    document.querySelectorAll('.finding mark[id^="evidence-"]').forEach(function (mark) {
      const target = documentView.querySelector("#" + CSS.escape(mark.id));
      if (!target) return;

      mark.setAttribute("role", "button");
      mark.setAttribute("tabindex", "0");
      mark.setAttribute("title", "Show this passage in the full document");

      function reveal() {
        target.scrollIntoView({
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "auto"
            : "smooth",
          block: "center",
        });
        focusElement(target);
      }

      mark.addEventListener("click", reveal);
      mark.addEventListener("keydown", function (event) {
        // Match native button behaviour: Enter and Space both activate.
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          reveal();
        }
      });
    });
  }
})();
