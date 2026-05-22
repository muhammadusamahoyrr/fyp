# SKILL: legal-core

## Purpose

The legal-core skill is the **entry point and orchestrator** of the entire Attorney.AI 3D system. It translates structured legal case data — clients, charges, evidence, parties, jurisdiction — into a normalized scene configuration that all downstream skills consume. No 3D asset, shader, or agent is invoked without passing through this skill first.

## Triggers

Activate this skill when:
- User provides a case description, legal scenario, or courtroom brief
- User says "generate a courtroom for [case type]"
- User requests a simulation, demonstration, or visualization of a legal proceeding
- Upstream data arrives from the Attorney.AI intake pipeline (ModIntake, case_repo)
- A new case document, PDF, or filing is loaded into the system

## Core Responsibilities

1. **Case Parsing** — Extract legal entities: judge, plaintiff, defendant, attorneys, jury, witnesses, evidence items
2. **Jurisdiction Mapping** — Determine courthouse style (federal, state, magistrate, international) from jurisdiction field
3. **Scene Config Generation** — Produce a `SceneConfig` JSON that all downstream skills read
4. **Timeline Sequencing** — Map case phases (opening → evidence → arguments → verdict) to simulation stages
5. **Agent Briefing** — Initialize prompts/personas for judge_agent and lawyer_agent

## SceneConfig Schema

```json
{
  "case_id": "string",
  "case_type": "criminal | civil | appellate | arbitration",
  "jurisdiction": "federal_us | state_us | uk_crown | international_icc",
  "courthouse_style": "neoclassical | modern | brutalist | colonial",
  "parties": {
    "judge": { "name": "string", "gender": "string" },
    "plaintiff_attorney": { "name": "string" },
    "defense_attorney": { "name": "string" },
    "jury": { "count": 12, "present": true },
    "witnesses": []
  },
  "evidence": [
    { "id": "string", "type": "document | physical | digital | testimony", "label": "string" }
  ],
  "phase": "intake | opening | evidence | cross_examination | closing | verdict",
  "mood": "neutral | tense | dramatic | solemn",
  "lighting_preset": "day_neutral | evening_dramatic | overcast_tense",
  "camera_preset": "establishing | closeup_judge | counsel_pov | jury_pov",
  "enable_physics": true,
  "enable_jury": true,
  "enable_gallery": false
}
```

## Rules (MUST follow)

1. **Never skip SceneConfig generation** — all downstream skills depend on it
2. **Always validate jurisdiction** before selecting courthouse style
3. **Mood must be derived from case type AND phase** — a verdict phase is always solemn, never "neutral"
4. **Evidence items must be typed** — untyped evidence defaults to "document"
5. **Do not invent case facts** — only use data provided by user or the intake pipeline
6. **Case ID must match the DB record** from `case_repo` if one exists

## Mood → Lighting Mapping

| Case Phase      | Mood      | Lighting Preset       |
|-----------------|-----------|----------------------|
| intake          | neutral   | day_neutral          |
| opening         | neutral   | day_neutral          |
| evidence        | tense     | overcast_tense       |
| cross_examination | tense   | evening_dramatic     |
| closing         | dramatic  | evening_dramatic     |
| verdict         | solemn    | evening_dramatic     |

## Jurisdiction → Courthouse Style

| Jurisdiction    | Style         | Notes                              |
|-----------------|---------------|-----------------------------------|
| federal_us      | neoclassical  | Columns, marble, symmetrical      |
| state_us        | modern        | Functional, glass, open plan      |
| uk_crown        | colonial      | Wood paneling, wigs, raised dock  |
| international   | brutalist     | Concrete, imposing, minimal ornamentation |
| magistrate      | modern        | Small, functional                 |

## Anti-Patterns

- **Do not** generate scene configs with missing `case_type` — this breaks courtroom-architecture
- **Do not** set `enable_jury: true` for arbitration cases
- **Do not** hard-code courthouse style — always derive from jurisdiction
- **Do not** pass raw case text to 3D skills — always normalize to SceneConfig first
- **Do not** modify the SceneConfig schema without updating all downstream SKILL.md files

## Integration Points

| Downstream Skill              | Consumes from SceneConfig          |
|-------------------------------|------------------------------------|
| courtroom-architecture        | courthouse_style, parties, enable_* |
| cinematic-environments        | mood, lighting_preset, camera_preset |
| shader-lighting-system        | lighting_preset, mood              |
| blender-procedural            | courthouse_style, evidence         |
| ai-legal-agent-workflows      | parties, phase, case_type          |
| legal-ui-dashboard            | case_id, parties, evidence, phase  |

## scripts/case_to_scene.py

```python
import json
from dataclasses import dataclass, asdict
from typing import Literal, List, Optional

MOOD_MAP = {
    "intake": "neutral", "opening": "neutral",
    "evidence": "tense", "cross_examination": "tense",
    "closing": "dramatic", "verdict": "solemn"
}

LIGHTING_MAP = {
    "neutral": "day_neutral",
    "tense": "overcast_tense",
    "dramatic": "evening_dramatic",
    "solemn": "evening_dramatic"
}

COURTHOUSE_MAP = {
    "federal_us": "neoclassical",
    "state_us": "modern",
    "uk_crown": "colonial",
    "international_icc": "brutalist",
    "magistrate": "modern"
}

def build_scene_config(case_data: dict) -> dict:
    jurisdiction = case_data.get("jurisdiction", "state_us")
    phase = case_data.get("phase", "intake")
    case_type = case_data.get("case_type", "civil")
    mood = MOOD_MAP.get(phase, "neutral")

    return {
        "case_id": case_data["case_id"],
        "case_type": case_type,
        "jurisdiction": jurisdiction,
        "courthouse_style": COURTHOUSE_MAP.get(jurisdiction, "modern"),
        "parties": case_data.get("parties", {}),
        "evidence": case_data.get("evidence", []),
        "phase": phase,
        "mood": mood,
        "lighting_preset": LIGHTING_MAP[mood],
        "camera_preset": "establishing",
        "enable_physics": True,
        "enable_jury": case_type not in ["arbitration"],
        "enable_gallery": False
    }
```
