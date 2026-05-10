<?xml version="1.0" encoding="UTF-8"?>
<mxGraphModel dx="1422" dy="762" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1000" pageHeight="1100" math="0" shadow="0">
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />

    <!-- TITLE -->
    <mxCell id="ttl" value="SD-1: Legal Query Intake &amp; AI Case Structuring  (M2 + M3)" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;fontSize=12;fontStyle=1;fontColor=#000000;" vertex="1" parent="1">
      <mxGeometry x="0" y="6" width="1000" height="24" as="geometry" />
    </mxCell>

    <!-- ═══ PARTICIPANT BOXES ═══ -->
    <mxCell id="p0" value="Client" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;fontStyle=1;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="10" y="36" width="120" height="36" as="geometry" />
    </mxCell>
    <mxCell id="p1" value="Frontend&#xa;(ModIntake / ModChatbot)" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;fontStyle=1;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="150" y="36" width="120" height="36" as="geometry" />
    </mxCell>
    <mxCell id="p2" value="CaseContext" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;fontStyle=1;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="290" y="36" width="120" height="36" as="geometry" />
    </mxCell>
    <mxCell id="p3" value="FastAPI" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;fontStyle=1;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="430" y="36" width="120" height="36" as="geometry" />
    </mxCell>
    <mxCell id="p4" value="intake_service /&#xa;case_service" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;fontStyle=1;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="570" y="36" width="120" height="36" as="geometry" />
    </mxCell>
    <mxCell id="p5" value="MongoDB" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;fontStyle=1;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="710" y="36" width="120" height="36" as="geometry" />
    </mxCell>
    <mxCell id="p6" value="WebSocket /&#xa;chat_socket.py" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;fontStyle=1;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="850" y="36" width="120" height="36" as="geometry" />
    </mxCell>

    <!-- ═══ LIFELINES ═══ -->
    <mxCell id="l0" style="endArrow=none;dashed=1;html=1;strokeColor=#000000;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="70" y="72" as="sourcePoint"/><mxPoint x="70" y="1080" as="targetPoint"/></mxGeometry>
    </mxCell>
    <mxCell id="l1" style="endArrow=none;dashed=1;html=1;strokeColor=#000000;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="210" y="72" as="sourcePoint"/><mxPoint x="210" y="1080" as="targetPoint"/></mxGeometry>
    </mxCell>
    <mxCell id="l2" style="endArrow=none;dashed=1;html=1;strokeColor=#000000;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="350" y="72" as="sourcePoint"/><mxPoint x="350" y="1080" as="targetPoint"/></mxGeometry>
    </mxCell>
    <mxCell id="l3" style="endArrow=none;dashed=1;html=1;strokeColor=#000000;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="490" y="72" as="sourcePoint"/><mxPoint x="490" y="1080" as="targetPoint"/></mxGeometry>
    </mxCell>
    <mxCell id="l4" style="endArrow=none;dashed=1;html=1;strokeColor=#000000;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="630" y="72" as="sourcePoint"/><mxPoint x="630" y="1080" as="targetPoint"/></mxGeometry>
    </mxCell>
    <mxCell id="l5" style="endArrow=none;dashed=1;html=1;strokeColor=#000000;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="770" y="72" as="sourcePoint"/><mxPoint x="770" y="1080" as="targetPoint"/></mxGeometry>
    </mxCell>
    <mxCell id="l6" style="endArrow=none;dashed=1;html=1;strokeColor=#000000;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="910" y="72" as="sourcePoint"/><mxPoint x="910" y="1080" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- ═══ PHASE 1 LABEL ═══ -->
    <mxCell id="ph1lbl" value="Phase 1 — M2: Legal Intake" style="text;html=1;strokeColor=#000000;fillColor=#D8D8D8;align=left;verticalAlign=middle;fontSize=9;fontStyle=1;" vertex="1" parent="1">
      <mxGeometry x="5" y="88" width="200" height="16" as="geometry" />
    </mxCell>

    <!-- m1: Client → Frontend -->
    <mxCell id="m1" value="1. Open /intake" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="70" y="110" as="sourcePoint"/><mxPoint x="210" y="110" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m2: Frontend → FastAPI -->
    <mxCell id="m2" value="2. POST /intake/start" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="210" y="134" as="sourcePoint"/><mxPoint x="490" y="134" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m3: FastAPI → intake_service -->
    <mxCell id="m3" value="start_intake(client_id)" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="490" y="158" as="sourcePoint"/><mxPoint x="630" y="158" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m4: intake_service → MongoDB -->
    <mxCell id="m4" value="Insert Intake {completed:false, step1-5:null, ai_structured_case.summary:pending}" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="630" y="182" as="sourcePoint"/><mxPoint x="770" y="182" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m5: MongoDB → intake_service ret -->
    <mxCell id="m5" value="{session_token}" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="770" y="204" as="sourcePoint"/><mxPoint x="630" y="204" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m6: intake_service → FastAPI ret -->
    <mxCell id="m6" value="{session_token}" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="630" y="224" as="sourcePoint"/><mxPoint x="490" y="224" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m7: FastAPI → Frontend ret -->
    <mxCell id="m7" value="{session_token}" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="490" y="244" as="sourcePoint"/><mxPoint x="210" y="244" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- LOOP FRAGMENT: Steps 1-5 -->
    <mxCell id="loopF" value="loop  [Steps 1–5]  Required fields: step1→province  step2→case_type,urgency  step3→incident_description  step4→(none)  step5→desired_outcome" style="rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#000000;dashed=1;align=left;verticalAlign=top;fontSize=8;fontStyle=1;" vertex="1" parent="1">
      <mxGeometry x="4" y="258" width="978" height="128" as="geometry" />
    </mxCell>

    <!-- m8: Client → Frontend (inside loop) -->
    <mxCell id="m8" value="Fill step N data (province / case_type+urgency / incident / evidence / outcome)" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="70" y="282" as="sourcePoint"/><mxPoint x="210" y="282" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m9: Frontend → FastAPI -->
    <mxCell id="m9" value="PATCH /intake/{token}/step/{N}  body:{data:{…}}" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="210" y="306" as="sourcePoint"/><mxPoint x="490" y="306" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m10: FastAPI → intake_service -->
    <mxCell id="m10" value="save_step(token, N, data) → _validate_step(N)" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="490" y="330" as="sourcePoint"/><mxPoint x="630" y="330" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m11: intake_service → MongoDB -->
    <mxCell id="m11" value="Update Intake.stepN" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="630" y="354" as="sourcePoint"/><mxPoint x="770" y="354" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m12: FastAPI → Frontend ret -->
    <mxCell id="m12" value="{current_step:N, completed:false, case_id:null}" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="490" y="378" as="sourcePoint"/><mxPoint x="210" y="378" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m13: Client → Frontend (Submit) -->
    <mxCell id="m13" value="Click  'Submit Case'" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="70" y="402" as="sourcePoint"/><mxPoint x="210" y="402" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m14: Frontend → FastAPI (convert) -->
    <mxCell id="m14" value="POST /intake/{token}/convert" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="210" y="426" as="sourcePoint"/><mxPoint x="490" y="426" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m15: FastAPI → intake_service -->
    <mxCell id="m15" value="convert_to_case(token, client_id)" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="490" y="450" as="sourcePoint"/><mxPoint x="630" y="450" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m16: intake_service → MongoDB (fetch + validate) -->
    <mxCell id="m16" value="Fetch intake → validate all step1-5 present (else AppValidationError)" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="630" y="474" as="sourcePoint"/><mxPoint x="770" y="474" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m17: MongoDB → intake_service ret -->
    <mxCell id="m17" value="intake document" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="770" y="494" as="sourcePoint"/><mxPoint x="630" y="494" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m18: intake_service → MongoDB (insert case) -->
    <mxCell id="m18" value="Insert Case {status:open, case_number:ATT-year-hex, lawyer_id:null, milestones:[], case_embedding:null}" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="630" y="518" as="sourcePoint"/><mxPoint x="770" y="518" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m19: MongoDB → intake_service ret (case_id) -->
    <mxCell id="m19" value="case_id" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="770" y="538" as="sourcePoint"/><mxPoint x="630" y="538" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m20: intake_service → MongoDB (mark completed) -->
    <mxCell id="m20" value="Mark Intake {completed:true, case_id}" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="630" y="562" as="sourcePoint"/><mxPoint x="770" y="562" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m21: intake_service → FastAPI ret -->
    <mxCell id="m21" value="{session_token, completed:true, case_id}" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="630" y="582" as="sourcePoint"/><mxPoint x="490" y="582" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m22: FastAPI → Frontend ret -->
    <mxCell id="m22" value="{case_id}" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="490" y="602" as="sourcePoint"/><mxPoint x="210" y="602" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m23: Frontend → CaseContext -->
    <mxCell id="m23" value="completeIntake({role, caseType, description, evidenceDocs}) → intakeDone=true" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="210" y="626" as="sourcePoint"/><mxPoint x="350" y="626" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m24: Frontend → Client ret (redirect) -->
    <mxCell id="m24" value="Redirect to /chat" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="210" y="648" as="sourcePoint"/><mxPoint x="70" y="648" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- PHASE SEPARATOR -->
    <mxCell id="sep" value="Phase 2 — M3: AI Legal Guidance (Chat via WebSocket)" style="text;html=1;strokeColor=#000000;fillColor=#D8D8D8;align=center;verticalAlign=middle;fontSize=9;fontStyle=1;" vertex="1" parent="1">
      <mxGeometry x="4" y="662" width="978" height="18" as="geometry" />
    </mxCell>

    <!-- m25: Client → Frontend -->
    <mxCell id="m25" value="Open /chat" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="70" y="694" as="sourcePoint"/><mxPoint x="210" y="694" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m26: Frontend → WebSocket/chat_socket -->
    <mxCell id="m26" value="WebSocket connect: ws://…/ws/chat/{session_id}?token=JWT" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="210" y="718" as="sourcePoint"/><mxPoint x="910" y="718" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m27: chat_socket → MongoDB (find/create session) -->
    <mxCell id="m27" value="decode_token(token) → find_or_create ChatSession {session_id, client_id}" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="910" y="742" as="sourcePoint"/><mxPoint x="770" y="742" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m28: WebSocket → Frontend (accepted) -->
    <mxCell id="m28" value="Connection accepted (greeting shown: Morning / Afternoon / Evening)" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="910" y="764" as="sourcePoint"/><mxPoint x="210" y="764" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m29: Client → Frontend (send) -->
    <mxCell id="m29" value="Type query (EN / UR) + click Send  [typing=true]" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="70" y="788" as="sourcePoint"/><mxPoint x="210" y="788" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m30: Frontend → WebSocket -->
    <mxCell id="m30" value="send({content, case_id, case_type, province})" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="210" y="812" as="sourcePoint"/><mxPoint x="910" y="812" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m31: chat_socket → MongoDB -->
    <mxCell id="m31" value="append_message(user) + update_session_meta(case_id, case_type, province)" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="910" y="836" as="sourcePoint"/><mxPoint x="770" y="836" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- NOTE: LangGraph TODO -->
    <mxCell id="todo" value="⚙ TODO: LangGraph supervisor invocation + token streaming (AI phase)" style="text;html=1;strokeColor=#000000;fillColor=#F0F0F0;align=center;verticalAlign=middle;fontSize=8;fontStyle=2;" vertex="1" parent="1">
      <mxGeometry x="620" y="852" width="372" height="16" as="geometry" />
    </mxCell>

    <!-- m32: chat_socket → WebSocket (stub response) -->
    <mxCell id="m32" value="{type:final, content:stub, citations:[], confidence:0.0}" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="910" y="876" as="sourcePoint"/><mxPoint x="210" y="876" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m33: Frontend → Client ret -->
    <mxCell id="m33" value="Display AI response  [typing=false, msg added to msgs[]]" style="edgeStyle=none;html=1;strokeColor=#000000;dashed=1;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="210" y="898" as="sourcePoint"/><mxPoint x="70" y="898" as="targetPoint"/></mxGeometry>
    </mxCell>

    <!-- m34: chat_socket → MongoDB (persist) -->
    <mxCell id="m34" value="append_message(assistant) — session persisted via checkpointer" style="edgeStyle=none;html=1;strokeColor=#000000;fontColor=#000000;fontSize=8;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;" edge="1" parent="1">
      <mxGeometry relative="1" as="geometry"><mxPoint x="910" y="922" as="sourcePoint"/><mxPoint x="770" y="922" as="targetPoint"/></mxGeometry>
    </mxCell>

  </root>
</mxGraphModel>
