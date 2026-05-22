# SKILL: ai-legal-agent-workflows

## Purpose

Orchestrates **multi-agent AI legal simulation** — judge, plaintiff lawyer, defense lawyer, and witness personas powered by LLMs. This skill manages turn-based dialogue, legal procedure sequencing, evidence objections, witness examination chains, and verdict generation. It connects the Claude API (or local LLM) to the 3D simulation loop.

## Architecture: Multi-Agent Court Sim

```
┌─────────────────────────────────────────────────────────────────┐
│                    AGENT ORCHESTRATOR                           │
│  (agent_router.py — manages turn order, phase, state)          │
└──────────┬──────────┬──────────────┬──────────────┬────────────┘
           │          │              │              │
    ┌──────▼──┐  ┌────▼────┐  ┌─────▼─────┐  ┌───▼──────┐
    │  JUDGE  │  │PLAINTIFF│  │  DEFENSE  │  │ WITNESS  │
    │  AGENT  │  │ATTORNEY │  │  ATTORNEY │  │  AGENT   │
    │         │  │  AGENT  │  │   AGENT   │  │          │
    └──────┬──┘  └────┬────┘  └─────┬─────┘  └───┬──────┘
           │          │              │              │
           └──────────┴──────────────┴──────────────┘
                                │
                    ┌───────────▼──────────────┐
                    │    LEGAL STATE MACHINE    │
                    │   (phase, evidence log,  │
                    │    objections, rulings)   │
                    └───────────────────────────┘
```

## Triggers

Activate when:
- User says "start the simulation", "run the trial", "let the judge speak"
- Phase changes and agents need to respond
- Evidence is submitted and objection/ruling flow is needed
- User wants AI to argue a case, cross-examine, or deliver a verdict
- Asking "what would the judge rule on this?"

## Agent Personas

### Judge Agent
```python
JUDGE_SYSTEM_PROMPT = """You are a federal judge presiding over a {case_type} case.
Case: {case_summary}
Current phase: {phase}
You uphold procedural rules strictly. You speak in formal, authoritative language.
You may: sustain/overrule objections, strike testimony, call recesses, deliver rulings.
You may NOT: advocate for either party, speculate about facts not in evidence.
Keep responses under 150 words unless delivering a final ruling.
"""
```

### Plaintiff Attorney Agent
```python
PLAINTIFF_ATTORNEY_PROMPT = """You are {name}, plaintiff's attorney in a {case_type} case.
Your client: {plaintiff_name}. Case theory: {case_theory}
Available evidence: {evidence_list}
Current phase: {phase}
You argue persuasively, cite evidence, and object to improper defense tactics.
Keep statements under 200 words unless delivering opening/closing.
"""
```

### Defense Attorney Agent
```python
DEFENSE_ATTORNEY_PROMPT = """You are {name}, defense attorney in a {case_type} case.
Your client: {defendant_name}. Defense theory: {defense_theory}
Available evidence: {evidence_list}
Current phase: {phase}
You challenge prosecution evidence, protect your client's rights, cross-examine witnesses.
Keep statements under 200 words unless delivering opening/closing.
"""
```

### Witness Agent
```python
WITNESS_SYSTEM_PROMPT = """You are {name}, a witness in a {case_type} case.
Your role: {witness_role}. Your relationship to the case: {relationship}
Known facts you can testify to: {known_facts}
You answer questions truthfully but only what you know.
You say "I don't know" or "I don't recall" when appropriate.
Never volunteer information not asked for.
"""
```

## Agent Router

```python
import anthropic
from dataclasses import dataclass
from typing import Literal, Optional, List
import json

client = anthropic.Anthropic()

@dataclass
class LegalTurn:
    speaker: Literal['judge', 'plaintiff', 'defense', 'witness']
    content: str
    phase: str
    action: Optional[str] = None  # 'objection', 'ruling', 'question', 'testimony'

class AgentRouter:
    def __init__(self, scene_config: dict):
        self.config = scene_config
        self.history: List[LegalTurn] = []
        self.phase = scene_config.get('phase', 'opening')
        self.evidence_admitted = []
        self.objection_pending = False

    def build_context(self) -> str:
        last_5 = self.history[-5:]
        return '\n'.join(f"{t.speaker.upper()}: {t.content}" for t in last_5)

    def call_agent(self, persona: str, prompt: str, context: str) -> str:
        response = client.messages.create(
            model='claude-opus-4-7',
            max_tokens=500,
            system=prompt,
            messages=[
                {"role": "user", "content": f"Court context:\n{context}\n\nYour turn."}
            ]
        )
        return response.content[0].text

    def judge_turn(self, trigger: str = None) -> LegalTurn:
        prompt = JUDGE_SYSTEM_PROMPT.format(
            case_type=self.config['case_type'],
            case_summary=self.config.get('case_summary', 'See evidence list'),
            phase=self.phase
        )
        context = self.build_context()
        if trigger:
            context += f"\n[TRIGGER: {trigger}]"
        text = self.call_agent('judge', prompt, context)
        turn = LegalTurn('judge', text, self.phase, 'ruling')
        self.history.append(turn)
        return turn

    def attorney_turn(self, side: str) -> LegalTurn:
        parties = self.config.get('parties', {})
        evidence_list = json.dumps([e['label'] for e in self.config.get('evidence', [])])
        attorney = parties.get(f'{side}_attorney', {})
        prompt = PLAINTIFF_ATTORNEY_PROMPT.format(
            name=attorney.get('name', 'Counsel'),
            case_type=self.config['case_type'],
            plaintiff_name=parties.get('plaintiff', {}).get('name', 'Plaintiff'),
            case_theory=self.config.get('case_theory', 'as argued'),
            evidence_list=evidence_list,
            phase=self.phase
        )
        text = self.call_agent(side, prompt, self.build_context())
        turn = LegalTurn(side, text, self.phase, 'statement')
        self.history.append(turn)
        return turn

    def run_phase(self, phase: str) -> List[LegalTurn]:
        self.phase = phase
        turns = []
        if phase == 'opening':
            turns.append(self.judge_turn("Call to order. Opening statements."))
            turns.append(self.attorney_turn('plaintiff'))
            turns.append(self.attorney_turn('defense'))
        elif phase == 'evidence':
            turns.append(self.attorney_turn('plaintiff'))
            # Simulate objection flow
            turns.append(self.attorney_turn('defense'))  # Objection
            turns.append(self.judge_turn("Objection raised by defense."))
        elif phase == 'verdict':
            turns.append(self.judge_turn("Deliver verdict."))
        return turns
```

## Objection / Ruling State Machine

```python
OBJECTION_TYPES = [
    'hearsay', 'relevance', 'speculation', 'leading',
    'badgered', 'assumes_facts', 'asked_and_answered'
]

RULING_RESPONSES = {
    'hearsay': ('sustained', "The statement is excluded as hearsay."),
    'relevance': ('sustained', "Objection sustained. Move on, counsel."),
    'leading': ('overruled', "Overruled. You may answer the question."),
    'speculation': ('sustained', "Sustained. The witness may not speculate.")
}

def handle_objection(objection_type: str, judge_agent: AgentRouter) -> dict:
    default = ('overruled', "Objection noted. Overruled.")
    ruling, statement = RULING_RESPONSES.get(objection_type, default)
    turn = LegalTurn('judge', statement, judge_agent.phase, ruling)
    judge_agent.history.append(turn)
    return {'ruling': ruling, 'statement': statement}
```

## Verdict Generation

```python
def generate_verdict(agent_router: AgentRouter) -> dict:
    """Generate a structured verdict from the judge agent."""
    trigger = """
    You have heard all arguments and evidence. Deliver your verdict.
    Format your response as:
    VERDICT: [GUILTY/NOT GUILTY/LIABLE/NOT LIABLE/IN FAVOR OF PLAINTIFF/IN FAVOR OF DEFENDANT]
    REASONING: [2-3 sentence explanation]
    SENTENCE/REMEDY: [If applicable]
    """
    turn = agent_router.judge_turn(trigger)
    # Parse structured verdict
    lines = turn.content.split('\n')
    verdict = {}
    for line in lines:
        if line.startswith('VERDICT:'):
            verdict['decision'] = line.replace('VERDICT:', '').strip()
        elif line.startswith('REASONING:'):
            verdict['reasoning'] = line.replace('REASONING:', '').strip()
        elif line.startswith('SENTENCE'):
            verdict['remedy'] = line.split(':', 1)[-1].strip()
    return verdict
```

## WebSocket Integration

```python
# Connect agent turns to real-time frontend via WebSocket
async def stream_trial_phase(websocket, agent_router: AgentRouter, phase: str):
    turns = agent_router.run_phase(phase)
    for turn in turns:
        await websocket.send_json({
            'type': 'agent_turn',
            'speaker': turn.speaker,
            'content': turn.content,
            'action': turn.action,
            'phase': turn.phase
        })
        await asyncio.sleep(2)  # Pace dialogue for UX
```

## Rules (MUST follow)

1. **Judge agent always speaks last** after objections — never interrupt judge
2. **Agents never reference real case law by citation** unless grounded in provided evidence
3. **Witness agents only know what's in `known_facts`** — they cannot invent testimony
4. **Defense and plaintiff agents must argue opposite positions** — router ensures this
5. **Verdict can only be called** after `closing` phase completes
6. **All agent output must be < 500 tokens** — prevents hallucination sprawl
7. **Objections must be typed** — untyped objections default to 'relevance'

## Anti-Patterns

- **Do not** give agents access to each other's system prompts
- **Do not** run all agents in parallel — legal procedure is sequential (turn-based)
- **Do not** allow agents to modify the SceneConfig — agents only produce dialogue
- **Do not** persist agent chat history beyond the current trial session
- **Do not** use GPT-3.5 or weaker models for judge — verdict quality degrades severely
- **Do not** let witness agent answer questions about events they weren't present for
- **Do not** stream agent output directly to 3D scene without sanitizing for XSS
