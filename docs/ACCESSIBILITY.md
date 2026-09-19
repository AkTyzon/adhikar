# Accessibility

The people most likely to need this tool are the least likely to have a lawyer,
and disability and legal vulnerability correlate. Treating accessibility as
polish would undercut the point of the project.

Target: **WCAG 2.2 level AA**.

## What was actually done

### Structure and navigation
- One `<h1>` per page; headings descend without skipping levels.
- Landmark elements throughout (`header`, `nav`, `main`, `footer`), each `nav`
  labelled.
- A skip link is the first focusable element on every page.
- `:target { scroll-margin-top }` so an in-page link never lands behind the header.

### Keyboard
- Every interactive element is reachable and operable by keyboard.
- Focus is never suppressed; `:focus-visible` gives a 3px outline in a colour
  that contrasts against every surface it can appear on.
- Evidence highlights are exposed as buttons with `role`, `tabindex`, and both
  Enter and Space handling, matching native button behaviour.
- The wide obligations table sits in a focusable scroll container so it can be
  scrolled without a pointer.

### Screen readers
- `aria-live="polite"` on the answer region: answers arrive after a round trip,
  and a live region announces the change without moving the user.
- Each highlight carries a visually hidden label naming *why* it is highlighted,
  so the reason is available without seeing the colour.
- Tables have captions and `scope` on every header cell.
- Form fields have real labels, `aria-describedby` hints, and `aria-invalid`
  when in error.
- The error summary receives focus on render and links to the field that failed.
- `aria-disabled` rather than `disabled` on a submitting button, so it stays in
  the accessibility tree and keeps announcing itself.

### Colour and contrast
- All text meets AA contrast in both light and dark themes. The severity colours
  were chosen against the card background, not against white.
- **Severity is never colour alone.** Each level carries a word ("Critical") and
  a distinct glyph (◆ ▲ ■ ● ○), so it survives greyscale printing and colour
  vision deficiency.
- Highlights are underlined as well as tinted; hidden-text highlights use a wavy
  underline, which is a second non-colour channel.
- `prefers-color-scheme` is honoured, and `forced-colors` (Windows High Contrast)
  has explicit rules so structure survives when the palette is replaced.

### Motion and preferences
- `prefers-reduced-motion` removes transitions rather than shortening them, and
  switches smooth scrolling to instant.
- All sizes in `rem`, so browser text-size settings work.
- Text is never justified — uneven word spacing creates rivers that measurably
  harm readability, particularly for dyslexic readers.

### Works without JavaScript
Every action is a plain form POST followed by a full server render. JavaScript
improves three things — focus management after a round trip, submission
feedback, and cross-linking evidence to the document view — and nothing depends
on it. This is an accessibility decision and a reliability one: a legal tool that
breaks when a script fails to load is a legal tool that breaks.

There is no inline script anywhere, which is also what allows the
Content-Security-Policy to omit `unsafe-inline`.

### Plain language
- Findings are written for someone reading their own contract: short sentences,
  no Latin, no "pursuant to".
- A glossary explains the legal terms that actually appear in the uploaded
  document.
- Numbers, periods and parties are never altered by simplification.

## Known gaps

Stated rather than glossed:

- **No automated a11y assertions in CI.** The markup was built to the checklist
  above and reviewed by hand; an axe-core run in a headless browser would be the
  right next step and is not implemented.
- **Not tested with real screen-reader users.** It has been checked against the
  specifications, which is not the same thing.
- **No interface language other than English.** The glossary makes legal English
  more approachable but does not translate. Multilingual output is the single
  highest-value accessibility improvement left for an Indian audience.
- **Scanned documents are refused, not OCR'd.** A user with an image-only PDF is
  told clearly rather than given a partial analysis, but they are still stuck.
