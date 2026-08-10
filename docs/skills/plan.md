# Plan Skill

Agentic multi-step coding plan creation and execution with a full staging pipeline.

**File:** `skills/plan.py`  
**Runner:** `scripts/plan_runner.py` (Redis daemon)

---

## How It Works

```
"build X"
    → build_simple_code_plan()    qwen3:14b generates structured plan
    → display plan for review
    → "proceed PLAN-ID"           queues steps to Redis jarvis:tasks
    → plan_runner executes each step
        ├── coding steps → qwen3.6:27b → staging/dev/PLAN-ID/
        └── test steps   → Playwright (simple) or Podman (complex)
    → staging/dev/ → staging/tested/
    → human approval → staging/tested/ → staging/approved/
```

## Commands

| Command | Description |
|---------|-------------|
| `build X` | Generate plan for task X |
| `proceed PLAN-ID` | Execute the plan |
| `cancel PLAN-ID` | Cancel and discard the plan |
| `modify plan — X` | Adjust plan before execution |

Plan commands bypass the memory router and go directly to the code route.

## Staging Directories

| Path | Description |
|------|-------------|
| `staging/dev/PLAN-ID/` | Files written during execution |
| `staging/tested/PLAN-ID/` | Passed automated tests |
| `staging/approved/PLAN-ID/` | Human-approved, ready to deploy |

## Approval

Approve via:
- **Codex UI** — approve button visible when `staging/tested/` exists
- **Telegram** — bot sends notification with approve/deny buttons
- **API** — `POST /api/plans/{id}/approve`

## Examples

```
"build a lottery website with 7x7 number grid"
"build a REST API for tracking expenses in Python"
"proceed PLAN-20260619-001"
"cancel PLAN-20260619-001"
```
