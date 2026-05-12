# Species Review Workflow

## Purpose

Prioritize and guide human review for AI-generated wildlife classifications.

## Review Priority Rules

| Condition | Priority |
|---|---|
| Rare or sensitive species | High |
| Low confidence | High |
| Conflicting model outputs | High |
| First detection for deployment | Medium |
| Routine high-confidence common species | Low |

## Output Format

Return review batches with media references, model labels, confidence, reason for review, and recommended reviewer action.

## Review States

Use `unreviewed`, `verified`, `corrected`, `rejected`, and `needs_review` consistently with the observation schema.
