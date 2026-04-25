# Skill: Accessibility (WCAG / Screen Reader / Keyboard)

## When to apply
The PRD specifies a new UI surface — a screen, modal, dialog, form, table,
chart, tooltip, or any interactive element — without calling out
accessibility requirements.

## Instruction to inject
For every new UI surface, verify the PRD addresses:

1. **Contrast (WCAG AA)** — text and meaningful non-text elements must
   meet 4.5:1 contrast for normal text and 3:1 for large text and icons.
   If the PRD specifies brand colors, check they clear AA on the intended
   backgrounds.
2. **Keyboard navigability** — every action must be reachable without a
   mouse. Tab order must be logical; focus state must be visible; no
   traps. Modals must restore focus on close.
3. **Screen-reader labels** — every interactive element has an
   accessible name; icons have aria-labels; images have alt text; form
   fields have explicit `<label>` associations.
4. **Non-color affordances** — error states, selected states, and
   required fields must be conveyed by more than color alone
   (icon + text, not "red = error" only).
5. **Motion and timing** — respect `prefers-reduced-motion`; any
   time-limited action has an extend / dismiss option.
6. **Touch target size** — interactive targets ≥ 44×44pt on mobile.

Severity guidance:
- **P0** for regulated contexts (gov, healthcare, finance, education)
  where lack of accessibility is a legal risk.
- **P1** for consumer products where a significant user cohort (screen
  reader, keyboard-only, low vision) would be excluded.
- **P2** for internal tools where accessibility is still a goal but not
  a launch gate.

## Rationale
Accessibility retrofits cost 10×–100× more than building it in. A PRD that
does not call out accessibility is a PRD that will ship inaccessible,
because the people who catch it (users of assistive tech, compliance
auditors) surface it only after launch. Forcing the question up front
normalizes the cost of a11y as part of the build budget.

## Examples of issues this catches
- New color palette that fails AA on the primary text/background pair.
- Modal with "X" button that has no aria-label; screen reader reads "button".
- Error messages shown only as red outlines; colorblind users miss them.
- Keyboard users cannot dismiss a toast; it auto-dismisses too fast.
- Icon-only buttons with no tooltip or accessible name.
- Drag-and-drop as the only interaction, no keyboard-equivalent.
