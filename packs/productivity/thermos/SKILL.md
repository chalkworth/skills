---
name: thermos
description: "Run two harsh reviews of a commit range in parallel, one for bugs, breakage and security and one for code quality, then merge their findings. Use for thermos, a thermo-nuclear review, or a deep audit of a branch or a period of history."
disable-model-invocation: true
argument-hint: "[base | A..B]"
---

# Thermos

Two subagents review the same commit range in the background, each with its own rubric. You
then merge what they find.

## Steps

1. Pick the range.
   - An argument of the form `A..B` is the range.
   - Any other argument is a base, and the range is `<base>...HEAD`.
   - With no argument, the base is the branch `git symbolic-ref refs/remotes/origin/HEAD` names.
     If that ref is not set, stop and ask for a base rather than assume `main`.

   If the range has no commits, say so and stop.

2. Gather the outline. Run `git diff --stat` and `git diff --name-only` over the range. Don't
   read the full diff yourself. The reviewers fetch it file by file, so a large range stays out
   of your context.

3. Start both reviewers. In one message, start two general-purpose subagents that run in the
   background. Give each one the range, the list of changed files and these instructions:
   - Read your rubric first and follow it in full. Wherever it says "branch" or "PR", it means
     this range.
   - Get the changes with `git diff <range> -- <path>`, and read whatever else in the repository
     you need to check a finding.
   - Don't start subagents of your own.
   - Return findings in the format below.

   The rubrics live in this skill's folder:
   - `references/review-rubric.md`: bugs, broken features, security, developer setup and
     feature-flag leaks.
   - `references/code-quality-rubric.md`: maintainability, structure, file size and simpler
     designs.

   Pass each reviewer its rubric's absolute path.

4. Merge. Wait for both reviewers.
   - If one failed or returned nothing, the first line of your answer is
     `Incomplete: <rubric file name>`, followed by what went wrong. Callers rely on this line.
   - Remove duplicate findings. A finding both reviewers raise carries more weight. Where they
     disagree, check the code and decide.
   - List findings with the highest priority first. If there are none, say "No findings."

## Finding format

```markdown
### P1: Retry loop never gives up when the token is expired
- **Where:** `src/client/session.py:88`
- **Evidence:** `refresh()` returns the same expired token, so the `while` loop at line 91 has
  no exit; the change at line 85 removed the attempt counter.
- **Remedy:** restore the attempt limit, and raise once it is reached.
- **Raised by:** both reviewers
```

Priorities run from P1 (fix before anything else) to P4 (worth doing when the code is next
touched).
