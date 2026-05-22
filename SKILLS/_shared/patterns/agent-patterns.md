# AI Agent Orchestration Patterns — Attorney.AI

## Pattern 1: Turn-Based Agent Loop
Never run agents in parallel — legal procedure is sequential.

```python
def run_trial_loop(router: AgentRouter, phases: list) -> list:
    all_turns = []
    for phase in phases:
        router.phase = phase
        turns = router.run_phase(phase)
        all_turns.extend(turns)
        # Gate: verdict only after closing
        if phase == 'closing':
            verdict = generate_verdict(router)
            all_turns.append(LegalTurn('judge', str(verdict), 'verdict', 'ruling'))
    return all_turns
```

## Pattern 2: Evidence-Grounded Agents
Agents only cite evidence IDs from the SceneConfig — no hallucinated citations.

```python
def build_evidence_context(scene_config: dict) -> str:
    items = scene_config.get('evidence', [])
    lines = [f"Exhibit {e['id']}: {e['label']} ({e['type']})" for e in items]
    return "Available evidence:\n" + '\n'.join(lines)
```

## Pattern 3: Phase State Machine
Legal phases can only advance forward, never skip to verdict.

```python
LEGAL_PHASE_ORDER = ['intake','opening','evidence','cross_examination','closing','verdict']

def advance_phase(current: str) -> str:
    idx = LEGAL_PHASE_ORDER.index(current)
    if idx < len(LEGAL_PHASE_ORDER) - 1:
        return LEGAL_PHASE_ORDER[idx + 1]
    return current  # Already at verdict

def can_advance_to_verdict(current: str) -> bool:
    return current == 'closing'
```

## Pattern 4: Objection Interrupt
Any agent output containing "OBJECTION" triggers judge intervention.

```python
def detect_objection(text: str) -> str | None:
    text_lower = text.lower()
    for obj_type in OBJECTION_TYPES:
        if obj_type.replace('_', ' ') in text_lower or 'objection' in text_lower:
            return obj_type
    return None

def process_turn(text: str, router: AgentRouter) -> list:
    turns = []
    obj = detect_objection(text)
    if obj:
        ruling = handle_objection(obj, router)
        turns.append(LegalTurn('judge', ruling['statement'], router.phase, ruling['ruling']))
    return turns
```

## Pattern 5: History Window Management
Keep agent context window manageable — prune to last N turns.

```python
MAX_HISTORY = 10

def pruned_context(history: list) -> list:
    return history[-MAX_HISTORY:]
```
