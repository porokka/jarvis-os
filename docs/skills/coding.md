# Coding Skill

Code generation, editing, and inspection via the active LLM backend.

**File:** `skills/coding.py` + `skills/coding_qwen3_coder.py`

---

## Tools

### code_edit

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task` | string | yes | Coding task description |
| `path` | string | no | File or project path |
| `code` | string | no | Existing source code or snippet to edit |
| `language` | string | no | Programming language hint |
| `model` | string | no | Override active model (e.g. `qwen3.6:27b`) |

Routes to `qwen3.6:27b` for code generation and file writes.

**Examples:**
```
"Add dark mode toggle to app/components/Header.tsx"
"Fix the TypeScript error in src/api/client.ts"
"Write a Python function to parse CSV with headers"
"Refactor the login form to use React Hook Form"
```

---

## Plan-Based Coding

For multi-file projects, use the [plan skill](plan.md) instead. The plan system:
1. Generates a structured 8-10 step plan
2. Runs each step with `qwen3.6:27b` via `plan_runner`
3. Writes files to `staging/dev/PLAN-ID/`
4. Runs automated tests before requesting approval

Direct `code_edit` is best for single-file edits and quick fixes.
