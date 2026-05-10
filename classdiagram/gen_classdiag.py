
def cls(id, x, y, w, h, name, attrs, ops, fill="#f8fafc", italic=False):
    fs = "3" if italic else "1"
    lines = []
    # Swimlane with rounded corners, shadow, nice font, slate border
    lines.append(f'<mxCell id="{id}" parent="1" style="swimlane;fontStyle={fs};align=center;verticalAlign=middle;childLayout=stackLayout;horizontal=1;startSize=36;horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=0;marginBottom=0;fillColor={fill};swimlaneFillColor=#ffffff;strokeColor=#334155;fontSize=14;fontFamily=Helvetica;strokeWidth=1.5;rounded=1;shadow=1;" value="{name}" vertex="1"><mxGeometry height="{h}" width="{w}" x="{x}" y="{y}" as="geometry" /></mxCell>')
    
    attr_lines = attrs.count('&#xa;') + 1
    ah = attr_lines * 20 + 10
    lines.append(f'<mxCell id="{id}A" parent="{id}" style="text;strokeColor=none;fillColor=none;align=left;verticalAlign=top;spacingLeft=12;spacingTop=8;overflow=hidden;rotatable=0;fontSize=12;fontFamily=Helvetica;fontColor=#1e293b;" value="{attrs}" vertex="1"><mxGeometry height="{ah}" width="{w}" y="36" as="geometry" /></mxCell>')
    
    dy = 36 + ah
    lines.append(f'<mxCell id="{id}D" parent="{id}" style="line;strokeWidth=1;fillColor=none;strokeColor=#cbd5e1;rotatable=0;" value="" vertex="1"><mxGeometry height="8" width="{w}" y="{dy}" as="geometry" /></mxCell>')
    
    dy += 8
    oh = len(ops.split("&#xa;")) * 20 + 8
    lines.append(f'<mxCell id="{id}O" parent="{id}" style="text;strokeColor=none;fillColor=none;align=left;verticalAlign=top;spacingLeft=12;spacingTop=6;overflow=hidden;rotatable=0;fontSize=12;fontFamily=Helvetica;fontColor=#1e293b;" value="{ops}" vertex="1"><mxGeometry height="{oh}" width="{w}" y="{dy}" as="geometry" /></mxCell>')
    return "\n".join(lines)

def edge(id, src, tgt, style, label="", src_mult="", tgt_mult="", pts=[]):
    pt_xml = ""
    if pts:
        arr = "".join([f'<mxPoint x="{p[0]}" y="{p[1]}" />' for p in pts])
        pt_xml = f'<Array as="points">{arr}</Array>'
    
    lbl = f' value="{label}"' if label else ''
    xml = f'<mxCell id="{id}" edge="1" parent="1" source="{src}" target="{tgt}" style="{style}"{lbl}><mxGeometry relative="1" as="geometry">{pt_xml}</mxGeometry></mxCell>'
    
    if src_mult:
        xml += f'\n<mxCell id="{id}_src" value="{src_mult}" style="edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];labelBackgroundColor=none;fontFamily=Helvetica;fontSize=12;fontColor=#475569;" vertex="1" connectable="0" parent="{id}"><mxGeometry x="-0.85" relative="1" as="geometry"><mxPoint as="offset" /></mxGeometry></mxCell>'
    if tgt_mult:
        xml += f'\n<mxCell id="{id}_tgt" value="{tgt_mult}" style="edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];labelBackgroundColor=none;fontFamily=Helvetica;fontSize=12;fontColor=#475569;" vertex="1" connectable="0" parent="{id}"><mxGeometry x="0.85" relative="1" as="geometry"><mxPoint as="offset" /></mxGeometry></mxCell>'
        
    return xml

GEN  = "endArrow=block;endSize=16;endFill=0;edgeStyle=orthogonalEdgeStyle;strokeColor=#475569;strokeWidth=1.5;"
COMP = "endArrow=diamond;endFill=1;edgeStyle=orthogonalEdgeStyle;strokeColor=#475569;strokeWidth=1.5;exitX=0;exitY=1;exitDx=0;exitDy=0;"
AGG  = "endArrow=diamond;endFill=0;edgeStyle=orthogonalEdgeStyle;strokeColor=#475569;strokeWidth=1.5;"
ASSO = "endArrow=none;edgeStyle=orthogonalEdgeStyle;strokeColor=#475569;strokeWidth=1.5;fontFamily=Helvetica;fontSize=12;fontColor=#334155;labelBackgroundColor=#ffffff;"

xml_parts = []
xml_parts.append('<mxGraphModel dx="1842" dy="758" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1654" pageHeight="1400" math="0" shadow="0"><root>')
xml_parts.append('<mxCell id="0" /><mxCell id="1" parent="0" />')
xml_parts.append('<mxCell id="title" parent="1" style="text;html=1;strokeColor=none;fillColor=none;align=center;fontSize=28;fontStyle=1;fontFamily=Helvetica;fontColor=#1e293b;" value="ATTORNEY.AI — Class Architecture" vertex="1"><mxGeometry height="50" width="600" x="480" y="10" as="geometry" /></mxCell>')

# ── USER
xml_parts.append(cls("User",580,80,260,295,"&lt;&lt;abstract&gt;&gt; User",
    "- id: String&#xa;- email: EmailStr&#xa;- password_hash: String&#xa;- full_name: String&#xa;- phone: String&#xa;- province: Province&#xa;- is_active: Boolean&#xa;- created_at: DateTime&#xa;- updated_at: DateTime",
    "+ register()&#xa;+ login()&#xa;+ resetPassword()",fill="#ffffff",italic=True))

# ── CLIENT
xml_parts.append(cls("Client",140,460,220,135,"Client",
    "- preferred_lang: String&#xa;- newsletter: Boolean",
    "+ submitIntake()",fill="#f5f5f5"))

# ── LAWYER
xml_parts.append(cls("Lawyer",580,460,260,240,"Lawyer",
    "- bar_number: String&#xa;- rating: Float&#xa;- availability: Boolean&#xa;- specializations: List&lt;String&gt;&#xa;- hourly_rate: Float&#xa;- years_of_experience: Integer",
    "+ acceptCase()&#xa;+ schedule()",fill="#f5f5f5"))

# ── ADMIN
xml_parts.append(cls("Admin",960,460,210,125,"Admin",
    "- (inherits User attributes)",
    "+ approveKYC()&#xa;+ manageUsers()",fill="#f5f5f5"))

# ── NOTIFICATION
xml_parts.append(cls("Notification",1050,80,250,235,"Notification",
    "- id: String&#xa;- user_id: String&#xa;- content: String&#xa;- type: NotificationType&#xa;- is_read: Boolean&#xa;- created_at: DateTime",
    "+ markAsRead()&#xa;+ dismiss()",fill="#f5f5f5"))

# ── CASEDOCUMENT
xml_parts.append(cls("Case",480,790,290,280,"CaseDocument",
    "- id: String&#xa;- case_number: String&#xa;- status: CaseStatus&#xa;- title: String&#xa;- milestones: List&lt;Milestone&gt;&#xa;- client_id: String&#xa;- lawyer_id: String&#xa;- created_at: DateTime",
    "+ updateStatus()&#xa;+ assignLawyer()",fill="#ffffff"))

# ── INTAKEDOCUMENT
xml_parts.append(cls("Intake",60,790,240,260,"IntakeDocument",
    "- id: String&#xa;- client_id: String&#xa;- dispute_type: String&#xa;- answers: JSON&#xa;- ai_summary: String&#xa;- status: IntakeStatus&#xa;- created_at: DateTime",
    "+ submit()&#xa;+ convertToCase()",fill="#ffffff"))

# ── APPOINTMENT
xml_parts.append(cls("Appointment",1050,780,260,295,"Appointment",
    "- id: String&#xa;- client_id: String&#xa;- lawyer_id: String&#xa;- case_id: String&#xa;- date_time: DateTime&#xa;- duration: Integer&#xa;- status: AppointmentStatus&#xa;- meeting_link: String",
    "+ book()&#xa;+ cancel()&#xa;+ reschedule()",fill="#f5f5f5"))

# ── AGREEMENTDOCUMENT
xml_parts.append(cls("Agreement",60,1200,260,260,"AgreementDocument",
    "- id: String&#xa;- case_id: String&#xa;- created_by: String&#xa;- type: AgreementType&#xa;- content: String&#xa;- signed_at: DateTime&#xa;- status: AgreementStatus",
    "+ sign()&#xa;+ revoke()",fill="#ffffff"))

# ── MILESTONE
xml_parts.append(cls("Milestone",460,1200,240,250,"Milestone",
    "- id: String&#xa;- case_id: String&#xa;- title: String&#xa;- description: String&#xa;- due_date: DateTime&#xa;- completed: Boolean",
    "+ markComplete()&#xa;+ updateDueDate()",fill="#ffffff"))

# ── DOCUMENT
xml_parts.append(cls("Document",750,1200,250,265,"Document",
    "- id: String&#xa;- case_id: String&#xa;- client_id: String&#xa;- file_name: String&#xa;- file_url: String&#xa;- doc_type: DocType&#xa;- uploaded_at: DateTime",
    "+ upload()&#xa;+ download()&#xa;+ delete()",fill="#ffffff"))

# ── CHATSESSION
xml_parts.append(cls("ChatSession",1060,1200,250,230,"ChatSession",
    "- id: String&#xa;- client_id: String&#xa;- case_id: String&#xa;- started_at: DateTime&#xa;- status: SessionStatus",
    "+ startSession()&#xa;+ endSession()&#xa;+ sendMessage()",fill="#f5f5f5"))

# ── INHERITANCE EDGES
xml_parts.append(edge("gen1","Client","User",GEN,pts=[(250,420),(710,420)]))
xml_parts.append(edge("gen2","Lawyer","User",GEN,pts=[(710,420)]))
xml_parts.append(edge("gen3","Admin","User",GEN,pts=[(1065,420),(710,420)]))

# ── ASSOCIATIONS
xml_parts.append(edge("r_cli_int","Client","Intake",ASSO,"submits","1","0..*",pts=[(170,595),(170,790)]))
xml_parts.append(edge("r_cli_case","Client","Case",ASSO,"owns","1","0..*",pts=[(280,595),(280,740),(530,740),(530,790)]))
xml_parts.append(edge("r_law_case","Lawyer","Case",ASSO,"handles","0..1","0..*",pts=[(710,700),(710,790)]))
xml_parts.append(edge("r_int_case","Intake","Case",ASSO,"convertsTo","1","0..1",pts=[(300,920),(480,920)]))
xml_parts.append(edge("r_user_notif","User","Notification",ASSO,"receives","1","0..*",pts=[(840,210),(1050,210)]))

# ── COMPOSITION (filled diamond) — CaseDocument owns
xml_parts.append(edge("r_case_agree","Case","Agreement",COMP,"contains","1","0..*",pts=[(530,1070),(530,1150),(190,1150),(190,1200)]))
xml_parts.append(edge("r_case_mile","Case","Milestone",COMP,"contains","1","0..*",pts=[(580,1070),(580,1200)]))

# ── AGGREGATION (hollow diamond)
xml_parts.append(edge("r_case_doc","Case","Document",AGG,"has","1","0..*",pts=[(680,1070),(680,1150),(875,1150),(875,1200)]))
xml_parts.append(edge("r_cli_doc","Client","Document",AGG,"owns","1","0..*",pts=[(140,550),(40,550),(40,1180),(800,1180),(800,1200)]))

# ── MORE ASSOCIATIONS
xml_parts.append(edge("r_cli_appt","Client","Appointment",ASSO,"books","1","0..*",pts=[(250,595),(250,750),(1150,750),(1150,780)]))
xml_parts.append(edge("r_law_appt","Lawyer","Appointment",ASSO,"hosts","1","0..*",pts=[(780,700),(780,730),(1100,730),(1100,780)]))
xml_parts.append(edge("r_case_appt","Case","Appointment",ASSO,"linkedTo","1","0..*",pts=[(770,930),(1050,930)]))
xml_parts.append(edge("r_cli_chat","Client","ChatSession",ASSO,"starts","1","0..*",pts=[(220,595),(220,760),(1350,760),(1350,1315),(1310,1315)]))
xml_parts.append(edge("r_case_chat","Case","ChatSession",ASSO,"attachedTo","1","0..*",pts=[(720,1070),(720,1120),(1185,1120),(1185,1200)]))
xml_parts.append(edge("r_agree_user","Agreement","User",ASSO,"createdBy","0..*","1",pts=[(60,1330),(20,1330),(20,50),(710,50),(710,80)]))

xml_parts.append('</root></mxGraphModel>')

output = "\n".join(xml_parts)
with open(r"C:\Users\The Laptop Hut\Desktop\attorney-ai\classdiagram\classdiag.drawio", "w", encoding="utf-8") as f:
    f.write(output)

print("classdiag.drawio generated successfully!")
print(f"Total size: {len(output)} bytes")
