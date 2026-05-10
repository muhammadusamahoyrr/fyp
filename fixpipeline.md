at << 'PYEOF' > /home/claude/generate_diagrams.py
import xml.etree.ElementTree as ET
import urllib.parse

def make_drawio(*pages):
    root = ET.Element("mxfile", host="app.diagrams.net")
    for name, content in pages:
        diagram = ET.SubElement(root, "diagram", name=name)
        diagram.text = content
    return ET.tostring(root, encoding="unicode", xml_declaration=False)

def encode(xml_str):
    return urllib.parse.quote(xml_str, safe='')

# We'll write raw XML directly - draw.io uncompressed format
def make_file():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="app.diagrams.net" version="21.0.0">

  <!-- ═══════════════════════════════════════════════════
       SD-1: Legal Intake & AI Chat (M2 + M3)
  ═══════════════════════════════════════════════════ -->
  <diagram name="SD-1 Legal Intake &amp; AI Chat">
    <mxGraphModel dx="1422" dy="762" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1654" pageHeight="1169" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>

        <!-- TITLE -->
        <mxCell id="t1" value="SD-1 — Legal Query Intake &amp; AI Case Structuring (M2 + M3)" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=16;fontStyle=1;" vertex="1" parent="1">
          <mxGeometry x="100" y="20" width="900" height="30" as="geometry"/>
        </mxCell>

        <!-- ── PARTICIPANTS ── -->
        <!-- Client -->
        <mxCell id="p1" value="Client" style="shape=mxgraph.flowchart.start_2;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="80" y="70" width="80" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p1l" value="" style="endArrow=none;dashed=1;strokeColor=#6c8ebf;exitX=0.5;exitY=1;" edge="1" source="p1" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="120" y="1250"/></Array></mxGeometry>
        </mxCell>

        <!-- ModIntake.jsx -->
        <mxCell id="p2" value="ModIntake.jsx" style="rounded=1;whiteSpace=wrap;fillColor=#fff2cc;strokeColor=#d6b656;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="240" y="70" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p2l" value="" style="endArrow=none;dashed=1;strokeColor=#d6b656;exitX=0.5;exitY=1;" edge="1" source="p2" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="300" y="1250"/></Array></mxGeometry>
        </mxCell>

        <!-- CaseContext.jsx -->
        <mxCell id="p3" value="CaseContext.jsx" style="rounded=1;whiteSpace=wrap;fillColor=#fff2cc;strokeColor=#d6b656;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="420" y="70" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p3l" value="" style="endArrow=none;dashed=1;strokeColor=#d6b656;exitX=0.5;exitY=1;" edge="1" source="p3" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="480" y="1250"/></Array></mxGeometry>
        </mxCell>

        <!-- FastAPI -->
        <mxCell id="p4" value="FastAPI /api/v1" style="rounded=1;whiteSpace=wrap;fillColor=#d5e8d4;strokeColor=#82b366;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="600" y="70" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p4l" value="" style="endArrow=none;dashed=1;strokeColor=#82b366;exitX=0.5;exitY=1;" edge="1" source="p4" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="660" y="1250"/></Array></mxGeometry>
        </mxCell>

        <!-- intake_service.py -->
        <mxCell id="p5" value="intake_service.py" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="790" y="70" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p5l" value="" style="endArrow=none;dashed=1;strokeColor=#b85450;exitX=0.5;exitY=1;" edge="1" source="p5" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="850" y="1250"/></Array></mxGeometry>
        </mxCell>

        <!-- case_service.py -->
        <mxCell id="p6" value="case_service.py" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="980" y="70" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p6l" value="" style="endArrow=none;dashed=1;strokeColor=#b85450;exitX=0.5;exitY=1;" edge="1" source="p6" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="1040" y="1250"/></Array></mxGeometry>
        </mxCell>

        <!-- MongoDB -->
        <mxCell id="p7" value="MongoDB" style="shape=cylinder3;whiteSpace=wrap;fillColor=#e1d5e7;strokeColor=#9673a6;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="1170" y="60" width="100" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="p7l" value="" style="endArrow=none;dashed=1;strokeColor=#9673a6;exitX=0.5;exitY=1;" edge="1" source="p7" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="1220" y="1250"/></Array></mxGeometry>
        </mxCell>

        <!-- WebSocket -->
        <mxCell id="p8" value="WebSocket /ws/chat" style="rounded=1;whiteSpace=wrap;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="1360" y="70" width="130" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p8l" value="" style="endArrow=none;dashed=1;strokeColor=#6c8ebf;exitX=0.5;exitY=1;" edge="1" source="p8" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="1425" y="1250"/></Array></mxGeometry>
        </mxCell>

        <!-- chat_socket.py -->
        <mxCell id="p9" value="chat_socket.py" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="1560" y="70" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p9l" value="" style="endArrow=none;dashed=1;strokeColor=#b85450;exitX=0.5;exitY=1;" edge="1" source="p9" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="1620" y="1250"/></Array></mxGeometry>
        </mxCell>

        <!-- ── PHASE 1 FRAME ── -->
        <mxCell id="fr1" value="&lt;b&gt;ref&lt;/b&gt; Phase 1 — M2 Legal Intake (5 Steps)" style="swimlane;startSize=25;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=11;fontStyle=1;opacity=20;" vertex="1" parent="1">
          <mxGeometry x="60" y="130" width="1320" height="580" as="geometry"/>
        </mxCell>

        <!-- Opens /intake -->
        <mxCell id="m1" value="Opens /intake" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="p1" target="p2">
          <mxGeometry y="20" relative="1" as="geometry"/>
        </mxCell>

        <!-- POST /intake/start -->
        <mxCell id="m2" value="POST /intake/start" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="p2" target="p4">
          <mxGeometry y="50" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m2a" value="start_intake(client_id)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="p4" target="p5">
          <mxGeometry y="70" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m2b" value="Insert Intake {step:1, completed:false}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p5" target="p7">
          <mxGeometry y="90" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m2c" value="intake saved" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#9673a6;fontSize=10;" edge="1" parent="1" target="p5">
          <mxGeometry y="110" relative="1" as="geometry"><mxPoint x="1220" y="260" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="m2d" value="{session_token}" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" target="p2">
          <mxGeometry y="130" relative="1" as="geometry"><mxPoint x="660" y="280" as="sourcePoint"/></mxGeometry>
        </mxCell>

        <!-- STEP 1 -->
        <mxCell id="step1_label" value="Step 1 — Role + Province" style="text;html=1;strokeColor=none;fillColor=#fff2cc;align=left;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=10;fontStyle=2;" vertex="1" parent="1">
          <mxGeometry x="70" y="295" width="160" height="20" as="geometry"/>
        </mxCell>
        <mxCell id="m3" value="Select role (Plaintiff|Defendant) + province" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="p1" target="p2">
          <mxGeometry y="150" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m4" value="PATCH /intake/{token}/step/1 {province}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="p2" target="p4">
          <mxGeometry y="170" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m4a" value="save_step(token,1,data)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="p4" target="p5">
          <mxGeometry y="190" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m4b" value="_validate_step(1) req:[province] ✓" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p5" target="p7">
          <mxGeometry y="210" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m4c" value="{current_step:1, completed:false}" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" target="p2">
          <mxGeometry y="230" relative="1" as="geometry"><mxPoint x="660" y="390" as="sourcePoint"/></mxGeometry>
        </mxCell>

        <!-- STEPS 2-5 summarized -->
        <mxCell id="step25_label" value="Steps 2–5 — Case Type, Incident, Evidence, Desired Outcome (same pattern: PATCH /intake/{token}/step/N → validate → DB → return)" style="text;html=1;strokeColor=#d6b656;fillColor=#fff2cc;align=left;verticalAlign=middle;whiteSpace=wrap;rounded=1;fontSize=10;" vertex="1" parent="1">
          <mxGeometry x="80" y="430" width="700" height="40" as="geometry"/>
        </mxCell>

        <!-- Submit / Convert -->
        <mxCell id="sub_label" value="Submit — Convert Intake to Case" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;fontSize=10;fontStyle=2;" vertex="1" parent="1">
          <mxGeometry x="70" y="490" width="200" height="20" as="geometry"/>
        </mxCell>
        <mxCell id="m10" value='Click "Submit Case"' style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="p1" target="p2">
          <mxGeometry y="380" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m11" value="POST /intake/{token}/convert" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="p2" target="p4">
          <mxGeometry y="400" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m12" value="convert_to_case(token, client_id)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="p4" target="p5">
          <mxGeometry y="420" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m12a" value="validate all 5 steps present" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p5" target="p7">
          <mxGeometry y="440" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m13" value="create_case(client_id, {case_type, province, title, intake_id})" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p5" target="p6">
          <mxGeometry y="460" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m13a" value="Insert Case {case_number:ATT-{year}-{hex}, status:open}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p6" target="p7">
          <mxGeometry y="480" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m13b" value="case_id" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#9673a6;fontSize=10;" edge="1" parent="1" target="p5">
          <mxGeometry y="500" relative="1" as="geometry"><mxPoint x="1220" y="650" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="m14" value="Mark Intake {completed:true, case_id}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p5" target="p7">
          <mxGeometry y="520" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m15" value="{case_id}" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" target="p2">
          <mxGeometry y="540" relative="1" as="geometry"><mxPoint x="660" y="690" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="m16" value="completeIntake({role,caseType,desc,evidenceDocs})" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="p2" target="p3">
          <mxGeometry y="560" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m17" value="Redirect to /chat" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" target="p1">
          <mxGeometry y="580" relative="1" as="geometry"><mxPoint x="300" y="720" as="sourcePoint"/></mxGeometry>
        </mxCell>

        <!-- ── PHASE 2 FRAME ── -->
        <mxCell id="fr2" value="&lt;b&gt;ref&lt;/b&gt; Phase 2 — M3 AI Legal Guidance (WebSocket Chat)" style="swimlane;startSize=25;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=11;fontStyle=1;opacity=20;" vertex="1" parent="1">
          <mxGeometry x="60" y="750" width="1620" height="460" as="geometry"/>
        </mxCell>

        <mxCell id="m20" value="Opens /chat (case context loaded)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="p1" target="p2">
          <mxGeometry y="630" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m21" value="WebSocket connect: ws://.../ws/chat/{session_id}?token=JWT" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="p2" target="p8">
          <mxGeometry y="650" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m22" value="Handshake — decode_token(token)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="p8" target="p9">
          <mxGeometry y="670" relative="1" as="geometry"/>
        </mxCell>

        <!-- alt frame -->
        <mxCell id="alt1" value="&lt;b&gt;alt&lt;/b&gt; [token invalid]" style="swimlane;startSize=20;fillColor=#f8cecc;strokeColor=#b85450;fontSize=10;opacity=30;" vertex="1" parent="1">
          <mxGeometry x="1330" y="840" width="320" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="alt1msg" value="close(code=4001)" style="text;html=1;fillColor=none;strokeColor=none;fontSize=10;" vertex="1" parent="alt1">
          <mxGeometry x="10" y="25" width="280" height="20" as="geometry"/>
        </mxCell>

        <mxCell id="m23" value="[token valid] find_by_session(session_id) or create ChatSession" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p9" target="p7">
          <mxGeometry y="710" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m24" value="Connection accepted" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" target="p2">
          <mxGeometry y="730" relative="1" as="geometry"><mxPoint x="1425" y="880" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="m25" value="Greeting shown (time-based: Morning/Afternoon/Evening)" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" target="p1">
          <mxGeometry y="750" relative="1" as="geometry"><mxPoint x="300" y="900" as="sourcePoint"/></mxGeometry>
        </mxCell>

        <mxCell id="m26" value="Type query (EN or UR) + click Send" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="p1" target="p2">
          <mxGeometry y="770" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m27" value="send({content, case_id, case_type, province})" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="p2" target="p8">
          <mxGeometry y="790" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m28" value="receive_json(data) → append_message(user)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="p8" target="p9">
          <mxGeometry y="810" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m29" value="append_message(session_id, {role:user, content})" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p9" target="p7">
          <mxGeometry y="830" relative="1" as="geometry"/>
        </mxCell>

        <!-- stub note -->
        <mxCell id="note1" value="⚠ TODO: LangGraph supervisor not yet connected — returns stub response" style="shape=callout;whiteSpace=wrap;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=10;" vertex="1" parent="1">
          <mxGeometry x="1330" y="990" width="320" height="50" as="geometry"/>
        </mxCell>

        <mxCell id="m30" value='send_json({type:"final", content:"AI not yet connected", citations:[], confidence:0.0})' style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="p9" target="p8">
          <mxGeometry y="860" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m31" value="AI response displayed (typing=false)" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" target="p1">
          <mxGeometry y="880" relative="1" as="geometry"><mxPoint x="1425" y="1030" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="m32" value="append_message(session_id, {role:assistant, content})" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p9" target="p7">
          <mxGeometry y="900" relative="1" as="geometry"/>
        </mxCell>

      </root>
    </mxGraphModel>
  </diagram>

  <!-- ═══════════════════════════════════════════════════
       SD-2: Lawyer Discovery & Appointment Booking (M4)
  ═══════════════════════════════════════════════════ -->
  <diagram name="SD-2 Lawyer Discovery &amp; Booking">
    <mxGraphModel dx="1422" dy="762" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1400" pageHeight="1169" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>

        <mxCell id="t1" value="SD-2 — Lawyer Discovery &amp; Appointment Booking (M4)" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=16;fontStyle=1;" vertex="1" parent="1">
          <mxGeometry x="100" y="20" width="800" height="30" as="geometry"/>
        </mxCell>

        <!-- Participants -->
        <mxCell id="p1" value="Client" style="shape=mxgraph.flowchart.start_2;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="60" y="70" width="80" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p1l" value="" style="endArrow=none;dashed=1;strokeColor=#6c8ebf;" edge="1" source="p1" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="100" y="1050"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="p2" value="ModLawyers.jsx" style="rounded=1;whiteSpace=wrap;fillColor=#fff2cc;strokeColor=#d6b656;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="220" y="70" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p2l" value="" style="endArrow=none;dashed=1;strokeColor=#d6b656;" edge="1" source="p2" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="280" y="1050"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="p3" value="FastAPI /api/v1" style="rounded=1;whiteSpace=wrap;fillColor=#d5e8d4;strokeColor=#82b366;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="400" y="70" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p3l" value="" style="endArrow=none;dashed=1;strokeColor=#82b366;" edge="1" source="p3" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="460" y="1050"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="p4" value="lawyer_service.py" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="580" y="70" width="130" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p4l" value="" style="endArrow=none;dashed=1;strokeColor=#b85450;" edge="1" source="p4" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="645" y="1050"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="p5" value="MongoDB" style="shape=cylinder3;whiteSpace=wrap;fillColor=#e1d5e7;strokeColor=#9673a6;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="770" y="60" width="100" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="p5l" value="" style="endArrow=none;dashed=1;strokeColor=#9673a6;" edge="1" source="p5" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="820" y="1050"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="p6" value="notification_service.py" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="940" y="70" width="150" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p6l" value="" style="endArrow=none;dashed=1;strokeColor=#b85450;" edge="1" source="p6" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="1015" y="1050"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="p7" value="Lawyer" style="shape=mxgraph.flowchart.start_2;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="1160" y="70" width="80" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="p7l" value="" style="endArrow=none;dashed=1;strokeColor=#6c8ebf;" edge="1" source="p7" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="1200" y="1050"/></Array></mxGeometry>
        </mxCell>

        <!-- Match flow -->
        <mxCell id="m1" value="Opens /lawyers (case_id in CaseContext)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="p1" target="p2">
          <mxGeometry y="20" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m2" value="GET /lawyers/match/{case_id}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="p2" target="p3">
          <mxGeometry y="50" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m3" value="Fetch Case by case_id" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="p3" target="p5">
          <mxGeometry y="80" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m3a" value="{case_type, province, summary}" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#9673a6;fontSize=10;" edge="1" parent="1" target="p3">
          <mxGeometry y="110" relative="1" as="geometry"><mxPoint x="820" y="210" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="m4" value="match_lawyers_for_case(case_id)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="p3" target="p4">
          <mxGeometry y="140" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m5" value="Fetch lawyers {province match, kyc_verified:true}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p4" target="p5">
          <mxGeometry y="170" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m5a" value="lawyer profiles" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#9673a6;fontSize=10;" edge="1" parent="1" target="p4">
          <mxGeometry y="200" relative="1" as="geometry"><mxPoint x="820" y="300" as="sourcePoint"/></mxGeometry>
        </mxCell>

        <!-- Score note -->
        <mxCell id="score_note" value="match_score = (rating/5.0)×0.5 + (0.2 if available) + 0.3&#xa;⚠ 0.3 = static placeholder (TODO: replace with cosine_sim)" style="shape=callout;whiteSpace=wrap;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=10;" vertex="1" parent="1">
          <mxGeometry x="580" y="370" width="380" height="50" as="geometry"/>
        </mxCell>

        <mxCell id="m6" value="Rank lawyers by score → top 5" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p4" target="p4">
          <mxGeometry y="230" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m7" value="Top 5 matched lawyers" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" target="p2">
          <mxGeometry y="270" relative="1" as="geometry"><mxPoint x="460" y="400" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="m8" value="Lawyer cards rendered (sorted by match score)" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" target="p1">
          <mxGeometry y="300" relative="1" as="geometry"><mxPoint x="280" y="430" as="sourcePoint"/></mxGeometry>
        </mxCell>

        <!-- Hire -->
        <mxCell id="m9" value='Click "Hire Lawyer"' style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="p1" target="p2">
          <mxGeometry y="340" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m10" value="PATCH /cases/{case_id} {assigned_lawyer_id, status:IN_PROGRESS}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="p2" target="p3">
          <mxGeometry y="360" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m11" value="Update Case {assigned_lawyer_id, status:IN_PROGRESS}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="p3" target="p5">
          <mxGeometry y="380" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m12" value="create_notification(lawyer_id, LAWYER_ASSIGNED)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="p3" target="p6">
          <mxGeometry y="400" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m12a" value="Insert Notification {type:LAWYER_ASSIGNED}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="p6" target="p5">
          <mxGeometry y="420" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="m12b" value='WebSocket push: "New case assigned"' style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" target="p7">
          <mxGeometry y="440" relative="1" as="geometry"><mxPoint x="1015" y="570" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="m13" value="Confirmation toast + redirect to /cases" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" target="p1">
          <mxGeometry y="460" relative="1" as="geometry"><mxPoint x="460" y="590" as="sourcePoint"/></mxGeometry>
        </mxCell>

        <!-- opt: Review -->
        <mxCell id="opt1" value="&lt;b&gt;opt&lt;/b&gt; [after engagement — client submits review]" style="swimlane;startSize=20;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=10;opacity=30;" vertex="1" parent="1">
          <mxGeometry x="60" y="630" width="800" height="100" as="geometry"/>
        </mxCell>
        <mxCell id="m14" value="Rate lawyer (1–5 stars)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="opt1">
          <mxGeometry y="20" relative="1" as="geometry"><mxPoint x="100" y="30" as="sourcePoint"/><mxPoint x="280" y="30" as="targetPoint"/></mxGeometry>
        </mxCell>
        <mxCell id="m15" value="POST /lawyers/{lawyer_id}/review {stars:4}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="opt1">
          <mxGeometry y="40" relative="1" as="geometry"><mxPoint x="280" y="50" as="sourcePoint"/><mxPoint x="460" y="50" as="targetPoint"/></mxGeometry>
        </mxCell>
        <mxCell id="m16" value="new_avg = (rating×total + stars)/(total+1) → Update lawyer_profile" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="opt1">
          <mxGeometry y="60" relative="1" as="geometry"><mxPoint x="460" y="70" as="sourcePoint"/><mxPoint x="645" y="70" as="targetPoint"/></mxGeometry>
        </mxCell>

      </root>
    </mxGraphModel>
  </diagram>

  <!-- ═══════════════════════════════════════════════════
       SD-3: Digital Agreement & E-Signature (M5)
  ═══════════════════════════════════════════════════ -->
  <diagram name="SD-3 Digital Agreement &amp; E-Signature">
    <mxGraphModel dx="1422" dy="762" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1400" pageHeight="1169" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>

        <mxCell id="t1" value="SD-3 — Digital Agreement &amp; E-Signature Workflow (M5)" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=16;fontStyle=1;" vertex="1" parent="1">
          <mxGeometry x="100" y="20" width="900" height="30" as="geometry"/>
        </mxCell>

        <!-- Participants -->
        <mxCell id="pc" value="Client" style="shape=mxgraph.flowchart.start_2;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="50" y="70" width="80" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="pcl" value="" style="endArrow=none;dashed=1;strokeColor=#6c8ebf;" edge="1" source="pc" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="90" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="pfe" value="ModAgreements.jsx" style="rounded=1;whiteSpace=wrap;fillColor=#fff2cc;strokeColor=#d6b656;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="200" y="70" width="140" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="pfel" value="" style="endArrow=none;dashed=1;strokeColor=#d6b656;" edge="1" source="pfe" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="270" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="papi" value="FastAPI /api/v1" style="rounded=1;whiteSpace=wrap;fillColor=#d5e8d4;strokeColor=#82b366;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="400" y="70" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="papil" value="" style="endArrow=none;dashed=1;strokeColor=#82b366;" edge="1" source="papi" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="460" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="pas" value="agreement_service.py" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="580" y="70" width="150" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="pasl" value="" style="endArrow=none;dashed=1;strokeColor=#b85450;" edge="1" source="pas" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="655" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="pdb" value="MongoDB" style="shape=cylinder3;whiteSpace=wrap;fillColor=#e1d5e7;strokeColor=#9673a6;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="790" y="60" width="100" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="pdbl" value="" style="endArrow=none;dashed=1;strokeColor=#9673a6;" edge="1" source="pdb" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="840" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="pns" value="notification_service.py" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="960" y="70" width="150" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="pnsl" value="" style="endArrow=none;dashed=1;strokeColor=#b85450;" edge="1" source="pns" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="1035" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="pl" value="Lawyer" style="shape=mxgraph.flowchart.start_2;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="1180" y="70" width="80" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="pll" value="" style="endArrow=none;dashed=1;strokeColor=#6c8ebf;" edge="1" source="pl" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="1220" y="1100"/></Array></mxGeometry>
        </mxCell>

        <!-- Phase 1: Create -->
        <mxCell id="fr1" value="&lt;b&gt;ref&lt;/b&gt; Phase 1 — Agreement Creation" style="swimlane;startSize=20;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=10;fontStyle=1;opacity=20;" vertex="1" parent="1">
          <mxGeometry x="40" y="130" width="1280" height="200" as="geometry"/>
        </mxCell>

        <mxCell id="a1" value='Opens "Create Agreement" for case' style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="pc" target="pfe">
          <mxGeometry y="50" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="a2" value="POST /agreements {case_id, lawyer_id, terms, template_type}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="pfe" target="papi">
          <mxGeometry y="80" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="a3" value="create_agreement(data)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="papi" target="pas">
          <mxGeometry y="110" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="a4" value="Insert Agreement {status:PENDING, parties:[{signed:false},{signed:false}], audit_log}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="pas" target="pdb">
          <mxGeometry y="140" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="a5" value="{agreement_id, status:PENDING}" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" target="pfe">
          <mxGeometry y="170" relative="1" as="geometry"><mxPoint x="460" y="340" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="a6" value="Show agreement terms view" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" target="pc">
          <mxGeometry y="190" relative="1" as="geometry"><mxPoint x="270" y="360" as="sourcePoint"/></mxGeometry>
        </mxCell>

        <!-- Phase 2: Client Signs -->
        <mxCell id="fr2" value="&lt;b&gt;ref&lt;/b&gt; Phase 2 — Client Signs" style="swimlane;startSize=20;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=10;fontStyle=1;opacity=20;" vertex="1" parent="1">
          <mxGeometry x="40" y="360" width="1280" height="300" as="geometry"/>
        </mxCell>

        <!-- alt: signature method -->
        <mxCell id="alt_sig" value="&lt;b&gt;alt&lt;/b&gt; [signature method]" style="swimlane;startSize=20;fillColor=#f8cecc;strokeColor=#b85450;fontSize=10;opacity=30;" vertex="1" parent="1">
          <mxGeometry x="60" y="390" width="380" height="100" as="geometry"/>
        </mxCell>
        <mxCell id="alt1t" value="CANVAS — ETO 2002 Advanced (S.2(d)(i))" style="text;fillColor=none;strokeColor=none;fontSize=10;" vertex="1" parent="alt_sig">
          <mxGeometry x="10" y="25" width="340" height="20" as="geometry"/>
        </mxCell>
        <mxCell id="alt2t" value="TYPED name — ETO 2002 Basic" style="text;fillColor=none;strokeColor=none;fontSize=10;" vertex="1" parent="alt_sig">
          <mxGeometry x="10" y="45" width="340" height="20" as="geometry"/>
        </mxCell>
        <mxCell id="alt3t" value="IMAGE_UPLOAD (PNG/JPG) — ETO 2002 Basic" style="text;fillColor=none;strokeColor=none;fontSize=10;" vertex="1" parent="alt_sig">
          <mxGeometry x="10" y="65" width="340" height="20" as="geometry"/>
        </mxCell>

        <mxCell id="b1" value="POST /agreements/{id}/sign {method, signature_data}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="pfe" target="papi">
          <mxGeometry y="240" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="b2" value="submit_signature(client_id, method, data)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="papi" target="pas">
          <mxGeometry y="260" relative="1" as="geometry"/>
        </mxCell>

        <mxCell id="guard_note" value="Guards: status != EXECUTED ✓  |  client not already signed ✓  |  classify ETO 2002" style="shape=callout;whiteSpace=wrap;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=10;" vertex="1" parent="1">
          <mxGeometry x="580" y="640" width="400" height="40" as="geometry"/>
        </mxCell>

        <mxCell id="b3" value="Update party {signed:true, signed_at, method, eto_classification}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="pas" target="pdb">
          <mxGeometry y="290" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="b4" value="Append audit_log {action:signed, party:client}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="pas" target="pdb">
          <mxGeometry y="310" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="b5" value="Check all signed? → NO" style="text;fillColor=none;strokeColor=none;fontSize=10;" vertex="1" parent="1">
          <mxGeometry x="580" y="700" width="200" height="20" as="geometry"/>
        </mxCell>
        <mxCell id="b6" value="create_notification(lawyer_id, AGREEMENT_SIGNED)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="papi" target="pns">
          <mxGeometry y="340" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="b7" value='WebSocket push to lawyer: "Awaiting your signature"' style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" target="pl">
          <mxGeometry y="360" relative="1" as="geometry"><mxPoint x="1035" y="730" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="b8" value='"Waiting for co-signer"' style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" target="pc">
          <mxGeometry y="380" relative="1" as="geometry"><mxPoint x="460" y="750" as="sourcePoint"/></mxGeometry>
        </mxCell>

        <!-- Phase 3: Lawyer Signs -->
        <mxCell id="fr3" value="&lt;b&gt;ref&lt;/b&gt; Phase 3 — Lawyer Signs → Auto-Execute" style="swimlane;startSize=20;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=10;fontStyle=1;opacity=20;" vertex="1" parent="1">
          <mxGeometry x="40" y="780" width="1280" height="280" as="geometry"/>
        </mxCell>

        <mxCell id="c1" value="Opens agreement from notification" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="pl" target="pfe">
          <mxGeometry y="460" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="c2" value="GET /agreements/{id}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="pfe" target="papi">
          <mxGeometry y="480" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="c3" value="POST /agreements/{id}/sign {method, signature_data}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="pfe" target="papi">
          <mxGeometry y="510" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="c4" value="submit_signature(lawyer_id, method, data)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="papi" target="pas">
          <mxGeometry y="530" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="c5" value="Guards pass → update_party + append_audit_log" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="pas" target="pdb">
          <mxGeometry y="550" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="c6" value="Re-fetch → all_signed = True → set_status(EXECUTED)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="pas" target="pdb">
          <mxGeometry y="570" relative="1" as="geometry"/>
        </mxCell>

        <mxCell id="exec_note" value="Agreement status → EXECUTED&#xa;Legally binding under ETO 2002" style="shape=callout;whiteSpace=wrap;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=10;" vertex="1" parent="1">
          <mxGeometry x="800" y="1030" width="260" height="50" as="geometry"/>
        </mxCell>

        <mxCell id="c7" value="{status:executed}" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" target="pfe">
          <mxGeometry y="600" relative="1" as="geometry"><mxPoint x="460" y="1050" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="c8" value="Notify client: Agreement fully executed" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="papi" target="pns">
          <mxGeometry y="620" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="c9" value='WebSocket push to client: "Fully executed"' style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" target="pc">
          <mxGeometry y="640" relative="1" as="geometry"><mxPoint x="1035" y="1090" as="sourcePoint"/></mxGeometry>
        </mxCell>

      </root>
    </mxGraphModel>
  </diagram>

  <!-- ═══════════════════════════════════════════════════
       SD-4: Document Automation & AI Drafting (M6)
  ═══════════════════════════════════════════════════ -->
  <diagram name="SD-4 Document Automation &amp; AI Drafting">
    <mxGraphModel dx="1422" dy="762" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1400" pageHeight="1169" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>

        <mxCell id="t1" value="SD-4 — Document Automation &amp; AI Drafting (M6)" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=16;fontStyle=1;" vertex="1" parent="1">
          <mxGeometry x="100" y="20" width="800" height="30" as="geometry"/>
        </mxCell>

        <!-- Participants -->
        <mxCell id="pu" value="Client" style="shape=mxgraph.flowchart.start_2;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="50" y="70" width="80" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="pul" value="" style="endArrow=none;dashed=1;strokeColor=#6c8ebf;" edge="1" source="pu" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="90" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="pfe2" value="ModDocuments.jsx" style="rounded=1;whiteSpace=wrap;fillColor=#fff2cc;strokeColor=#d6b656;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="200" y="70" width="130" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="pfe2l" value="" style="endArrow=none;dashed=1;strokeColor=#d6b656;" edge="1" source="pfe2" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="265" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="papi2" value="FastAPI /api/v1" style="rounded=1;whiteSpace=wrap;fillColor=#d5e8d4;strokeColor=#82b366;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="390" y="70" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="papi2l" value="" style="endArrow=none;dashed=1;strokeColor=#82b366;" edge="1" source="papi2" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="450" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="pds" value="document_service.py" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="570" y="70" width="140" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="pdsl" value="" style="endArrow=none;dashed=1;strokeColor=#b85450;" edge="1" source="pds" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="640" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="ptpl" value="docxtpl (thread pool)" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="770" y="70" width="140" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="ptpll" value="" style="endArrow=none;dashed=1;strokeColor=#b85450;" edge="1" source="ptpl" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="840" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="plo" value="LibreOffice --headless" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="970" y="70" width="140" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="plol" value="" style="endArrow=none;dashed=1;strokeColor=#b85450;" edge="1" source="plo" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="1040" y="1100"/></Array></mxGeometry>
        </mxCell>

        <mxCell id="pdb2" value="MongoDB" style="shape=cylinder3;whiteSpace=wrap;fillColor=#e1d5e7;strokeColor=#9673a6;fontStyle=1;fontSize=11;" vertex="1" parent="1">
          <mxGeometry x="1170" y="60" width="100" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="pdb2l" value="" style="endArrow=none;dashed=1;strokeColor=#9673a6;" edge="1" source="pdb2" parent="1">
          <mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="1220" y="1100"/></Array></mxGeometry>
        </mxCell>

        <!-- Generate request -->
        <mxCell id="d1" value="Select template + fill fields (plaintiff, facts, relief_sought...)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="pu" target="pfe2">
          <mxGeometry y="20" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="dtodo" value="⚠ TODO: fields currently filled manually — LLM auto-extraction planned for AI phase" style="shape=callout;whiteSpace=wrap;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=10;" vertex="1" parent="1">
          <mxGeometry x="200" y="140" width="400" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="d2" value='Click "Generate Document"' style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="pu" target="pfe2">
          <mxGeometry y="60" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="d3" value="POST /documents/generate {case_id, template_type, fields}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="pfe2" target="papi2">
          <mxGeometry y="80" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="d4" value="generate_document(case_id, client_id, template_type, fields)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="papi2" target="pds">
          <mxGeometry y="100" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="d5" value="Insert Document {status:pending, file_path:null}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="pds" target="pdb2">
          <mxGeometry y="120" relative="1" as="geometry"/>
        </mxCell>

        <!-- alt: template missing -->
        <mxCell id="alt_tmpl" value="&lt;b&gt;alt&lt;/b&gt; [template file missing]" style="swimlane;startSize=20;fillColor=#f8cecc;strokeColor=#b85450;fontSize=10;opacity=30;" vertex="1" parent="1">
          <mxGeometry x="570" y="320" width="680" height="70" as="geometry"/>
        </mxCell>
        <mxCell id="atm1" value="raise AppValidationError → mark_failed(doc_id) → re-raise → 422 to client" style="text;fillColor=none;strokeColor=none;fontSize=10;" vertex="1" parent="alt_tmpl">
          <mxGeometry x="10" y="25" width="640" height="20" as="geometry"/>
        </mxCell>

        <!-- else: template exists -->
        <mxCell id="d6" value="[template exists] asyncio.to_thread → DocxTemplate.render(fields).save(doc_id.docx)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="pds" target="ptpl">
          <mxGeometry y="180" relative="1" as="geometry"/>
        </mxCell>

        <!-- alt: docxtpl fails -->
        <mxCell id="alt_docx" value="&lt;b&gt;alt&lt;/b&gt; [docxtpl rendering fails]" style="swimlane;startSize=20;fillColor=#f8cecc;strokeColor=#b85450;fontSize=10;opacity=30;" vertex="1" parent="1">
          <mxGeometry x="770" y="440" width="480" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="adf1" value="mark_failed(doc_id) → does NOT re-raise → {status:failed} to client" style="text;fillColor=none;strokeColor=none;fontSize=10;" vertex="1" parent="alt_docx">
          <mxGeometry x="10" y="25" width="440" height="20" as="geometry"/>
        </mxCell>

        <mxCell id="d7" value="[rendering ok] doc_id.docx saved" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" target="pds">
          <mxGeometry y="230" relative="1" as="geometry"><mxPoint x="840" y="530" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="d8" value="asyncio.to_thread → libreoffice --headless --convert-to pdf" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="pds" target="plo">
          <mxGeometry y="260" relative="1" as="geometry"/>
        </mxCell>

        <!-- alt: LO fails -->
        <mxCell id="alt_lo" value="&lt;b&gt;alt&lt;/b&gt; [LibreOffice fails]" style="swimlane;startSize=20;fillColor=#f8cecc;strokeColor=#b85450;fontSize=10;opacity=30;" vertex="1" parent="1">
          <mxGeometry x="970" y="620" width="400" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="alf1" value="logger.error → mark_failed(doc_id) → {status:failed} — does NOT re-raise" style="text;fillColor=none;strokeColor=none;fontSize=10;" vertex="1" parent="alt_lo">
          <mxGeometry x="10" y="25" width="360" height="20" as="geometry"/>
        </mxCell>

        <mxCell id="d9" value="[conversion ok] doc_id.pdf written → delete intermediate .docx" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" target="pds">
          <mxGeometry y="310" relative="1" as="geometry"><mxPoint x="1040" y="700" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="d10" value="update_file_path(doc_id, uploads/docs/doc_id.pdf) → status:generated" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="pds" target="pdb2">
          <mxGeometry y="340" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="d11" value="{doc_id, status:generated}" style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" target="pfe2">
          <mxGeometry y="370" relative="1" as="geometry"><mxPoint x="450" y="840" as="sourcePoint"/></mxGeometry>
        </mxCell>
        <mxCell id="d12" value='"Download PDF" button enabled + WebSocket notification: DOCUMENT_READY' style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" target="pu">
          <mxGeometry y="400" relative="1" as="geometry"><mxPoint x="265" y="870" as="sourcePoint"/></mxGeometry>
        </mxCell>

        <!-- Download -->
        <mxCell id="dl_label" value="── Download ──" style="text;html=1;fillColor=none;strokeColor=none;fontSize=11;fontStyle=2;" vertex="1" parent="1">
          <mxGeometry x="50" y="900" width="120" height="20" as="geometry"/>
        </mxCell>
        <mxCell id="d13" value='Click "Download PDF"' style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#6c8ebf;fontSize=10;" edge="1" parent="1" source="pu" target="pfe2">
          <mxGeometry y="460" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="d14" value="GET /documents/{doc_id}/download" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="pfe2" target="papi2">
          <mxGeometry y="480" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="d15" value="get_document(doc_id) → verify client_id → check file_path exists" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="papi2" target="pdb2">
          <mxGeometry y="500" relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="d16" value='FileResponse(path, media_type="application/pdf", filename="{title}.pdf")' style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;dashed=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" target="pu">
          <mxGeometry y="530" relative="1" as="geometry"><mxPoint x="265" y="1000" as="sourcePoint"/></mxGeometry>
        </mxCell>

      </root>
    </mxGraphModel>
  </diagram>

  <!-- ═══════════════════════════════════════════════════
       ST-1: Case Lifecycle
  ═══════════════════════════════════════════════════ -->
  <diagram name="ST-1 Case Lifecycle">
    <mxGraphModel dx="1422" dy="762" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1100" pageHeight="900" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="t1" value="ST-1 — Case Lifecycle (entity: Case.status in MongoDB)" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=16;fontStyle=1;" vertex="1" parent="1">
          <mxGeometry x="100" y="20" width="800" height="30" as="geometry"/>
        </mxCell>

        <mxCell id="s0" value="" style="ellipse;fillColor=#000000;strokeColor=#000000;" vertex="1" parent="1"><mxGeometry x="490" y="70" width="20" height="20" as="geometry"/></mxCell>
        <mxCell id="s1" value="INTAKE" style="rounded=1;whiteSpace=wrap;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="440" y="120" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s2" value="OPEN" style="rounded=1;whiteSpace=wrap;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="440" y="220" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s3" value="PENDING_LAWYER" style="rounded=1;whiteSpace=wrap;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="240" y="330" width="140" height="44" as="geometry"/></mxCell>
        <mxCell id="s4" value="IN_PROGRESS" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="610" y="330" width="140" height="44" as="geometry"/></mxCell>
        <mxCell id="s5" value="CLOSED" style="rounded=1;whiteSpace=wrap;fillColor=#e1d5e7;strokeColor=#9673a6;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="240" y="490" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s6" value="DISMISSED" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="610" y="490" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="send" value="" style="ellipse;fillColor=#000000;strokeColor=#000000;strokeWidth=3;" vertex="1" parent="1"><mxGeometry x="426" y="600" width="28" height="28" as="geometry"/></mxCell>
        <mxCell id="sendi" value="" style="ellipse;fillColor=#ffffff;strokeColor=#000000;" vertex="1" parent="1"><mxGeometry x="430" y="604" width="20" height="20" as="geometry"/></mxCell>

        <mxCell id="e01" value="client starts intake" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#333;fontSize=10;" edge="1" parent="1" source="s0" target="s1"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e12" value="convert_to_case() success&#xa;Case: ATT-{year}-{hex}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#333;fontSize=10;" edge="1" parent="1" source="s1" target="s2"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e23a" value="no lawyer yet" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="s2" target="s3"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e23b" value="lawyer hired directly&#xa;assigned_lawyer_id set" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s2" target="s4"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e34" value="client hires lawyer&#xa;PATCH /cases/{id}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="s3" target="s4"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e44" value="milestone / hearing added" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s4" target="s4"><mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="800" y="352"/><mxPoint x="800" y="352"/></Array></mxGeometry></mxCell>
        <mxCell id="e45a" value="lawyer marks resolved&#xa;PATCH status=CLOSED" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#9673a6;fontSize=10;" edge="1" parent="1" source="s4" target="s5"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e45b" value="court / admin dismisses" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s4" target="s6"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e25a" value="client abandons" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#9673a6;fontSize=10;" edge="1" parent="1" source="s2" target="s5"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e35" value="client cancels" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#9673a6;fontSize=10;" edge="1" parent="1" source="s3" target="s5"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="ef5" value="" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#333;fontSize=10;" edge="1" parent="1" source="s5" target="send"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="ef6" value="" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#333;fontSize=10;" edge="1" parent="1" source="s6" target="send"><mxGeometry relative="1" as="geometry"/></mxCell>
      </root>
    </mxGraphModel>
  </diagram>

  <!-- ═══════════════════════════════════════════════════
       ST-2: Agreement Lifecycle
  ═══════════════════════════════════════════════════ -->
  <diagram name="ST-2 Agreement Lifecycle">
    <mxGraphModel dx="1422" dy="762" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="900" pageHeight="700" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="t1" value="ST-2 — Agreement Lifecycle (entity: Agreement.status)" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=16;fontStyle=1;" vertex="1" parent="1">
          <mxGeometry x="100" y="20" width="700" height="30" as="geometry"/>
        </mxCell>

        <mxCell id="s0" value="" style="ellipse;fillColor=#000000;strokeColor=#000000;" vertex="1" parent="1"><mxGeometry x="340" y="65" width="20" height="20" as="geometry"/></mxCell>
        <mxCell id="s1" value="PENDING" style="rounded=1;whiteSpace=wrap;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=13;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="290" y="110" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s1note" value="Party 1 or Party 2 can sign in any order.&#xa;Guard prevents double-sign.&#xa;Guard: status != EXECUTED" style="text;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=10;align=left;" vertex="1" parent="1"><mxGeometry x="440" y="110" width="260" height="44" as="geometry"/></mxCell>

        <mxCell id="s2" value="EXECUTED" style="rounded=1;whiteSpace=wrap;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=13;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="290" y="280" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s2note" value="Legally binding under ETO 2002&#xa;CANVAS = Advanced (S.2(d)(i))&#xa;TYPED/IMAGE = Basic" style="text;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=10;align=left;" vertex="1" parent="1"><mxGeometry x="440" y="280" width="260" height="44" as="geometry"/></mxCell>

        <mxCell id="s3" value="CANCELLED" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontSize=13;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="80" y="280" width="120" height="44" as="geometry"/></mxCell>

        <mxCell id="send" value="" style="ellipse;fillColor=#000000;strokeColor=#000000;strokeWidth=3;" vertex="1" parent="1"><mxGeometry x="283" y="390" width="28" height="28" as="geometry"/></mxCell>
        <mxCell id="sendi" value="" style="ellipse;fillColor=#ffffff;strokeColor=#000000;" vertex="1" parent="1"><mxGeometry x="287" y="394" width="20" height="20" as="geometry"/></mxCell>

        <mxCell id="e01" value="POST /agreements&#xa;create_agreement()" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#333;fontSize=10;" edge="1" parent="1" source="s0" target="s1"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e11" value="1st party signs (CANVAS/TYPED/IMAGE)&#xa;ETO 2002 classified, other party notified" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="s1" target="s1"><mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="430" y="132"/><mxPoint x="430" y="132"/></Array></mxGeometry></mxCell>
        <mxCell id="e12" value="2nd party signs → all_signed=True&#xa;auto-transition by service" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="s1" target="s2"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e13" value="either party cancels" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s1" target="s3"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="ef2" value="" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#333;" edge="1" parent="1" source="s2" target="send"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="ef3" value="" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#333;" edge="1" parent="1" source="s3" target="send"><mxGeometry relative="1" as="geometry"/></mxCell>
      </root>
    </mxGraphModel>
  </diagram>

  <!-- ═══════════════════════════════════════════════════
       ST-3: Lawyer KYC Lifecycle
  ═══════════════════════════════════════════════════ -->
  <diagram name="ST-3 Lawyer KYC Lifecycle">
    <mxGraphModel dx="1422" dy="762" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1000" pageHeight="800" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="t1" value="ST-3 — Lawyer KYC Lifecycle (entity: User.kyc_verified bool + LawyerProfile)" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=16;fontStyle=1;" vertex="1" parent="1">
          <mxGeometry x="80" y="20" width="840" height="30" as="geometry"/>
        </mxCell>

        <mxCell id="s0" value="" style="ellipse;fillColor=#000000;strokeColor=#000000;" vertex="1" parent="1"><mxGeometry x="390" y="65" width="20" height="20" as="geometry"/></mxCell>
        <mxCell id="s1" value="REGISTERED" style="rounded=1;whiteSpace=wrap;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="340" y="110" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s1n" value="kyc_verified=false&#xa;Account locked" style="text;fontSize=10;strokeColor=#6c8ebf;fillColor=#dae8fc;" vertex="1" parent="1"><mxGeometry x="490" y="110" width="140" height="44" as="geometry"/></mxCell>

        <mxCell id="s2" value="PENDING_KYC" style="rounded=1;whiteSpace=wrap;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="340" y="210" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s2n" value="Visible in GET /admin/kyc/pending&#xa;Admin checks pbbarcouncil.com / ibc.org.pk" style="text;fontSize=10;strokeColor=#d6b656;fillColor=#fff2cc;" vertex="1" parent="1"><mxGeometry x="490" y="210" width="260" height="44" as="geometry"/></mxCell>

        <mxCell id="s3" value="VERIFIED_ACTIVE" style="rounded=1;whiteSpace=wrap;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="540" y="320" width="140" height="44" as="geometry"/></mxCell>
        <mxCell id="s3n" value="kyc_verified=true&#xa;All features unlocked" style="text;fontSize=10;strokeColor=#82b366;fillColor=#d5e8d4;" vertex="1" parent="1"><mxGeometry x="700" y="320" width="160" height="44" as="geometry"/></mxCell>

        <mxCell id="s4" value="KYC_REJECTED" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="140" y="320" width="130" height="44" as="geometry"/></mxCell>
        <mxCell id="s4n" value="kyc_rejection_reason set&#xa;Lawyer can resubmit" style="text;fontSize=10;strokeColor=#b85450;fillColor=#f8cecc;" vertex="1" parent="1"><mxGeometry x="0" y="320" width="130" height="44" as="geometry"/></mxCell>

        <mxCell id="s5" value="SUSPENDED" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="540" y="430" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s6" value="DEACTIVATED" style="rounded=1;whiteSpace=wrap;fillColor=#e1d5e7;strokeColor=#9673a6;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="340" y="540" width="120" height="44" as="geometry"/></mxCell>

        <mxCell id="send" value="" style="ellipse;fillColor=#000000;strokeColor=#000000;strokeWidth=3;" vertex="1" parent="1"><mxGeometry x="386" y="650" width="28" height="28" as="geometry"/></mxCell>
        <mxCell id="sendi" value="" style="ellipse;fillColor=#ffffff;strokeColor=#000000;" vertex="1" parent="1"><mxGeometry x="390" y="654" width="20" height="20" as="geometry"/></mxCell>

        <mxCell id="e01" value="POST /auth/register {role:LAWYER}" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#333;fontSize=10;" edge="1" parent="1" source="s0" target="s1"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e12" value="submits KYC docs&#xa;(enrollment_no, CNIC, bar_council)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="s1" target="s2"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e23a" value="PATCH /admin/kyc/{id} {approved:true}&#xa;kyc_verified=true → KYC_APPROVED" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="s2" target="s3"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e23b" value="PATCH /admin/kyc/{id} {approved:false}&#xa;kyc_rejection_reason set → KYC_REJECTED" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s2" target="s4"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e42" value="resubmits corrected docs" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="s4" target="s2"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e35" value="admin suspends&#xa;(policy violation)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s3" target="s5"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e53" value="admin reinstates" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="s5" target="s3"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e36" value="lawyer self-deactivates" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#9673a6;fontSize=10;" edge="1" parent="1" source="s3" target="s6"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="ef5" value="permanent ban" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s5" target="send"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="ef6" value="" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#9673a6;" edge="1" parent="1" source="s6" target="send"><mxGeometry relative="1" as="geometry"/></mxCell>
      </root>
    </mxGraphModel>
  </diagram>

  <!-- ═══════════════════════════════════════════════════
       ST-4: AI Chat Session Lifecycle
  ═══════════════════════════════════════════════════ -->
  <diagram name="ST-4 AI Chat Session Lifecycle">
    <mxGraphModel dx="1422" dy="762" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1100" pageHeight="900" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="t1" value="ST-4 — AI Chat Session Lifecycle (entity: WebSocket session + ModChatbot.jsx)" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=16;fontStyle=1;" vertex="1" parent="1">
          <mxGeometry x="80" y="20" width="900" height="30" as="geometry"/>
        </mxCell>

        <mxCell id="s0" value="" style="ellipse;fillColor=#000000;strokeColor=#000000;" vertex="1" parent="1"><mxGeometry x="490" y="65" width="20" height="20" as="geometry"/></mxCell>

        <mxCell id="s1" value="PAGE_LOADED" style="rounded=1;whiteSpace=wrap;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="440" y="110" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s2" value="CONNECTING" style="rounded=1;whiteSpace=wrap;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="440" y="200" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s2f" value="CONNECTION_FAILED" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="640" y="200" width="140" height="44" as="geometry"/></mxCell>
        <mxCell id="s3" value="CONNECTED" style="rounded=1;whiteSpace=wrap;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="440" y="300" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s4" value="AWAITING_INPUT" style="rounded=1;whiteSpace=wrap;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="440" y="400" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s5" value="PROCESSING" style="rounded=1;whiteSpace=wrap;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="440" y="500" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s6" value="RESPONSE_COMPLETE" style="rounded=1;whiteSpace=wrap;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="440" y="600" width="140" height="44" as="geometry"/></mxCell>
        <mxCell id="s7" value="DISCONNECTED" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="240" y="400" width="120" height="44" as="geometry"/></mxCell>
        <mxCell id="s8" value="HALLUCINATION_BLOCKED" style="rounded=1;whiteSpace=wrap;fillColor=#f8cecc;strokeColor=#b85450;fontSize=12;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="640" y="500" width="160" height="44" as="geometry"/></mxCell>

        <mxCell id="stubNote" value="⚠ LangGraph stub: PROCESSING returns stub response&#xa;(LangGraph supervisor not yet connected)" style="shape=callout;whiteSpace=wrap;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=10;" vertex="1" parent="1"><mxGeometry x="640" y="590" width="300" height="50" as="geometry"/></mxCell>

        <mxCell id="send" value="" style="ellipse;fillColor=#000000;strokeColor=#000000;strokeWidth=3;" vertex="1" parent="1"><mxGeometry x="486" y="710" width="28" height="28" as="geometry"/></mxCell>
        <mxCell id="sendi" value="" style="ellipse;fillColor=#ffffff;strokeColor=#000000;" vertex="1" parent="1"><mxGeometry x="490" y="714" width="20" height="20" as="geometry"/></mxCell>

        <mxCell id="e01" value="user navigates to /chat" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#333;fontSize=10;" edge="1" parent="1" source="s0" target="s1"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e12" value="ModChatbot mounts&#xa;WebSocket.connect()" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="s1" target="s2"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e22f" value="network error / server down" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s2" target="s2f"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="ef22" value="auto-reconnect" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="s2f" target="s2"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e23" value="handshake success&#xa;LangGraph checkpointer loaded" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="s2" target="s3"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e34" value="ready — greeting shown" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="s3" target="s4"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e45" value="user sends message" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="s4" target="s5"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e56" value='server sends {type:"final"}&#xa;turn complete' style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="s5" target="s6"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e58" value="hallucination_node fails" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s5" target="s8"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e84" value="warning shown — user can retry" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s8" target="s4"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e64" value="session persisted&#xa;ready for next msg" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#82b366;fontSize=10;" edge="1" parent="1" source="s6" target="s4"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e47" value="user closes / server timeout" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s4" target="s7"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e37" value="network drop" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#b85450;fontSize=10;" edge="1" parent="1" source="s3" target="s7"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="e72" value="reconnect&#xa;(session_id preserved)" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#d6b656;fontSize=10;" edge="1" parent="1" source="s7" target="s2"><mxGeometry relative="1" as="geometry"/></mxCell>
        <mxCell id="ef7" value="user navigates away" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;endFill=1;strokeColor=#333;fontSize=10;" edge="1" parent="1" source="s7" target="send"><mxGeometry relative="1" as="geometry"/></mxCell>

      </root>
    </mxGraphModel>
  </diagram>

</mxfile>'''
    return xml

content = make_file()
with open('/mnt/user-data/outputs/ATTORNEY_AI_Diagrams.drawio', 'w', encoding='utf-8') as f:
    f.write(content)
print("Done! File written.")
print(f"Size: {len(content)} chars")
PYEOF
python3 /home/claude/generate_diagrams.py