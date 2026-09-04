# Editor story Workflow

This file records the workflow and orchestration process. Read this file before
making or reviewing changes. Story specs, phase decisions, and scope boundaries belong in `docs/milestones.md`; high-level design belongs in `docs/design-spec.md`.

## Workflow

0. Ask a `senior-coder` subagent to create a detailed plan for the next milestone, and break it down into stories that can be worked on by a junior engineer. The plan will be saved in `docs/milestones.md`. For simple milestones, the plan can have a single story.
1. For each story, give a `coder` subagent the story spec verbatim from `docs/milestones.md`, the scope boundary and decisions from that file, exact file paths, and the per-story verification commands. Include the Required Coder-Prompt Rules below.
2. Trust the coder's reported verification. Do not repeat it.
3. Give a lean, read-only `reviewer` the same story spec, scope boundary, and diff. The reviewer reads the diff and existing code, verifies architectural claims but makes no changes and doesn't run tests or lint.
4. Send findings back to the same coder agent with `SendMessage`, then re-review the fix, until the reviewer
   greenlights the story.
5. Stage only story files and commit with a concise gitmoji message. Update the status table in
   `docs/milestones.md` in a separate small documentation commit.
6. Do not let a subagent start the next story, commit changes, or edit phase-summary files before the final
   cleanup story.

## Roles

| Role | Responsibility |
| --- | --- |
| Senior Coder | Creates story plans, breaks down milestones into stories, and resolves architectural questions. |
| Coder | Runs scoped fmt, lint, type checks, tests, and bundle per the active story spec. Reports results; does not boot the app. |
| Reviewer | Read-only diff inspection and targeted searches only. Does not run any tools, including app/browser checks. |
| Orchestrator | Trusts the coder's reported commands; does not repeat verification. Handles commit and status updates. |
| User | Owns app/browser and smoke verification. Subagents do not boot the app. |

## Required Coder-Prompt Rules

Every coder story dispatch must include these explicit rules:

- **"Do NOT boot the editor or run any browser/smoke test."** State this negative explicitly.
- **"NEVER use `git stash`, `git checkout --`, or `git restore` on any file you did not intentionally edit for
  this task. If something unexpected changes, STOP and report it."** Never self-heal with destructive git
  commands.
- If a coder is stuck on an architectural decision, tell it to escalate to `senior-coder` rather than guess.

## Other Locked Decisions

These apply across all editor work, not just the current phase:

| Decision | Choice |
| --- | --- |
| Component authoring | JSX in `.tsx` files; `jsx: "react-jsx"`, `jsxImportSource: "preact"` |
| Focus-safe external DOM writes | `useLayoutEffect` plus ref and `document.activeElement` guard, with uncontrolled inputs |
| Dialogs | Native `<dialog>` driven by `showModal()`/`close()` through a ref |

## Review Lessons

The reviewer has caught defects that tests, type checks, and lint missed:

- **Cross-bundle DOM assumptions.** Before treating a DOM node as Preact-owned, check whether another
  app also loads the module. Static DOM consumers may otherwise stop receiving updates.
- **Async races.** Moving imperative DOM work into state can introduce close-and-reopen hazards; use a
  request-generation counter when responses may arrive out of order.
- **Weak tests.** Ensure assertions prove the operation occurred rather than merely matching initial
  state.
