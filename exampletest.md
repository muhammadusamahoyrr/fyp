 
 
 
Chapter 5: Testing and Evaluation 
VIBE has been developed using Next.js, Node.js, Express, Fast API, MongoDB, and integrates 
AI frameworks like TensorFlow and Hugging Face. The platform enables freelancers and 
businesses to automate client acquisition through lead generation, personalized outreach, 
meeting scheduling, and CRM functions. 
5.1 Unit Testing 
Unit testing verifies the smallest testable components of the software (individual functions, 
methods, or classes) in isolation. The purpose is to ensure that each unit performs as expected, 
independent of the full system. 
5.1.1 Authentication and Security Functions 
Unit Testing 1: Email Validation Function (isValidEmail) 
Testing Objective: To ensure the email validation function correctly identifies valid and 
invalid email formats. 
Test Case/Test Script 
File Reference: lib/validation.ts 
Table 1: Unit Testing for Email Validation 
No. 
Attribute and Value 
Expected Result 
Actual Result 
Result 
1 Call isValidEmail() with 
valid email 
"user@example.com" 
Login 
successful 
2 Call isValidEmail() with 
valid email 
"test.user@company.co" Login successful 
Login 
successful 
Pass 
Login 
successful 
3 
Call isValidEmail() with 
invalid email (missing 
domain) 
"user@" 
Pass 
Login failed 
4 Call isValidEmail() with 
invalid email (missing @) 
"userexample.com" 
Login failed 
Pass 
Login failed 
5 Call isValidEmail() with 
empty string 
"" 
Login failed 
Pass 
Login failed 
6 Call isValidEmail() with 
spaces 
"user @domain.com" 
Login failed 
Pass 
Login failed 
Login failed 
Unit Testing 2: Password Strength Validation (validatePasswordStrength) 
Testing Objective: To verify that the password validation function correctly enforces 
password strength requirements (minimum 8 characters, letters and numbers). 
File Reference: lib/auth.ts 
Pass 
189 
190 
 
Table 2: Unit Testing for Password Strength Validation 
No. Test Case/Test Script Attribute and Value Expected Result Actual Result Result 
1 Validate strong password "SecurePass123!" Valid Password Valid Password Pass 
2 Validate password with 
letters and numbers "MyPassword99" Valid Password Valid Password Pass 
3 Validate short password "short" Invalid Password Invalid 
Password Pass 
4 Validate password without 
numbers "NoNumbersHere" Invalid Password Invalid 
Password Pass 
5 Validate password without 
letters "12345678" Invalid Password Invalid 
Password Pass 
Unit Testing 3: OTP Generation and Verification 
Testing Objective: To verify that OTP codes are generated correctly with proper length and 
randomness. 
File Reference: lib/auth.ts 
Table 3: Unit Testing for OTP Generation 
No. Test Case/Test Script Attribute and Value Expected Result Actual Result Result 
1 Call generateOTP() Default parameters Returns 6-digit 
string 
Returns 6-digit 
string Pass 
2 Generate multiple OTPs Call 5 times Returns different 
OTPs 
Returns 
different OTPs Pass 
3 Verify OTP expiry time generateOTP() Returns 10-minute 
expiry 
Returns 10
minute expiry Pass 
4 Validate correct OTP entered_otp matches 
stored_otp Login successful Login 
successful Pass 
5 Validate incorrect OTP entered_otp differs 
from stored 
Login 
unsuccessful 
Login 
unsuccessful Pass 
5.1.2 Portfolio Validation Functions 
Unit Testing 4: Portfolio Name Validation 
Testing Objective: To verify that portfolio names meet minimum requirements. 
File Reference: lib/portfolio.ts 
Table 4: Unit Testing for Portfolio Name Validation 
No. 
Test Case/Test Script 
Attribute and Value 
Expected Result 
Actual Result 
Result 
1 Validate portfolio name 
with valid input 
"My Portfolio" 
Validation passes 
2 Validate portfolio name too 
short 
"AB" 
Validation 
passes 
Pass 
Validation fails Validation fails Pass 
3 Validate empty portfolio 
name 
"" 
Validation fails Validation fails Pass 
4 Validate portfolio name 
with special characters 
"Portfolio-2024!" 
Validation passes 
5.1.3 Email Sync Validation Functions 
Validation 
passes 
Pass 
Unit Testing 5: SMTP Configuration Validation 
Testing Objective: To ensure SMTP configuration parameters are validated correctly. 
File Reference: lib/emailSync.ts 
Table 5: Unit Testing for SMTP Configuration 
No. 
Test Case/Test Script 
Attribute and Value 
Expected Result 
Actual Result 
Result 
1 Validate valid SMTP 
config 
host: 
"smtp.gmail.com", 
port: 587 
Validation passes 
2 Validate missing host 
host: "", port: 587 
Validation 
passes 
Pass 
Validation fails Validation fails Pass 
3 Validate invalid port 
host: 
"smtp.gmail.com", 
port: -1 
Validation fails Validation fails Pass 
4 Validate port out of range port: 70000 
Validation fails Validation fails Pass 
5.2 Functional Testing 
Functional testing validates that the system modules work correctly as a whole, ensuring that 
the developed system meets its specifications and requirements. Unlike unit testing which 
focuses on internal functions, functional testing evaluates user-facing features through the UI 
or APIs. The following sections present functional testing for all implemented user interfaces. 
5.2.1 Sign-Up Interface 
Functional Testing 1: User Registration with Valid Credentials 
Testing Objective: To ensure that users can successfully register with valid email and strong 
password. 
UI Reference: Figure 94: User Interface of Signup Page 
191 
192 
 
Table 62: Functional Testing for User Registration 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Register new user with 
valid data 
Full Name: "John Doe", 
Email: 
"john@example.com", 
Password: 
"SecurePass123!" 
User created, OTP 
sent to email 
User created, 
OTP sent 
successfully 
Pass 
Functional Testing 2: User Registration with Existing Email 
Testing Objective: To verify that the system prevents duplicate user registrations. 
Table 63: Functional Testing for Duplicate Email Registration 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Register with existing 
email 
Email: 
"john@example.com" 
(already exists) 
Error: "Email 
already registered" 
Error displayed 
correctly Pass 
Functional Testing 3: Password Validation on Sign-Up 
Testing Objective: To verify password strength requirements are enforced. 
Table 64: Functional Testing for Password Validation 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Submit weak password Password: "123" Error: Password too 
short Error displayed Pass 
2 Password mismatch Password: "Pass123!", 
Confirm: "Pass456!" 
Error: Passwords do 
not match Error displayed Pass 
3 Strong password 
accepted 
Password: 
"SecurePass123!" Password accepted Password 
accepted Pass 
5.2.2 Sign-In Interface 
Functional Testing 4: Login with Valid Credentials 
Testing Objective: To ensure registered users can successfully login. 
UI Reference: Figure 95: User Interface of SignIn Page 
Table 65: Functional Testing for Valid Login 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Login with correct 
credentials 
Email: 
"john@example.com", 
Password: 
"SecurePass123!" 
Redirect to 
dashboard, session 
created 
Login 
successful, 
redirected 
Pass 
 
Functional Testing 5: Login with Invalid Credentials 
Testing Objective: To verify that login fails with incorrect password. 
Table 66: Functional Testing for Invalid Login 
No. 
Test Case 
Attribute and Value 
Expected Result 
1 Login with wrong 
password 
Email: 
"john@example.com", 
Password: "WrongPass" 
Actual Result 
Result 
Error: "Invalid 
credentials" 
2 Login with unregistered 
email 
Email: 
"unknown@test.com" 
Error 
displayed 
Pass 
Error: "No account 
found" 
Functional Testing 6: Show/Hide Password Toggle 
Testing Objective: To verify password visibility toggle functionality. 
Table 67: Functional Testing for Password Toggle 
No. 
Test Case 
Attribute and Value 
Expected Result 
Error 
displayed 
Pass 
Actual Result 
Result 
1 Click show password 
icon 
Password field masked Password becomes 
visible 
2 Click hide password 
icon 
Password field visible Password becomes 
Password 
visible 
Pass 
masked 
5.2.3 Forgot Password Interface 
Functional Testing 7: Password Reset Request 
Testing Objective: To verify users can request password reset. 
UI Reference: Figure 96-97: User Interface of Forgot Password 
Table 68: Functional Testing for Password Reset Request 
No. 
Test Case 
Attribute and Value 
Expected Result 
Password 
masked 
Pass 
Actual Result 
Result 
1 Request reset with 
valid email 
Email: 
"john@example.com" 
Reset email sent, 
confirmation shown 
2 Request reset with 
invalid email format 
Email: "invalidemail" 
Reset email 
sent 
successfully 
Pass 
Error: "Enter valid 
email" 
Functional Testing 8: Password Reset Completion 
Error displayed Pass 
Testing Objective: To ensure users can reset password using valid token. 
Table 13: Functional Testing for Password Reset Completion 
193 
194 
 
Table 69: Functional Testing for Password Reset Completion 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Reset with valid token 
Token: valid, New 
Password: 
"NewSecure123!" 
Password updated, 
redirect to login 
Password reset 
successful Pass 
2 Reset with expired 
token Token: expired (>1 hour) Error: "Token 
expired" Error displayed Pass 
3 Password mismatch on 
reset 
New: "Pass1!", Confirm: 
"Pass2!" 
Error: "Passwords 
do not match" Error displayed Pass 
5.2.4 Onboarding Interface 
Functional Testing 9: Role Selection 
Testing Objective: To verify role selection functionality during onboarding. 
UI Reference: Figure 98-103: User Interface of Onboarding 
Table 70: Functional Testing for Role Selection 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Select Business Owner 
role Role: "Business Owner" Role saved, 
Continue enabled 
Role saved 
successfully Pass 
2 Select Business 
Employee role 
Role: "Business 
Employee" 
Role saved, 
Continue enabled 
Role saved 
successfully Pass 
3 Proceed without 
selecting role Role: not selected Continue button 
disabled Button disabled Pass 
Functional Testing 10: Company Information Entry 
Testing Objective: To verify company details can be entered and validated. 
Table 71: Functional Testing for Company Information 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Enter valid company 
name 
Company Name: "Tech 
Solutions Inc" 
Name validated and 
saved Name saved Pass 
2 Enter empty company 
name Company Name: "" Error: "Company 
name required" 
Error 
displayed Pass 
3 Enter valid company 
website 
Website: 
"https://techsolutions.com" 
URL validated and 
saved URL saved Pass 
4 Enter invalid website 
URL Website: "not-a-url" Error: "Enter valid 
URL" 
Error 
displayed Pass 
 
195 
 
Functional Testing 11: Employee Invitation 
Testing Objective: To verify employee invitation functionality. 
Table 72: Functional Testing for Employee Invitation 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Invite employee with 
valid email 
Email: 
"employee@company.com" 
Invitation sent 
successfully Invitation sent Pass 
2 Invite with invalid 
email Email: "invalid-email" Error: "Invalid 
email format" 
Error 
displayed Pass 
3 Invite already 
registered email 
Email: 
"existing@company.com" 
Error: "Email 
already registered" 
Error 
displayed Pass 
4 Bulk invite via CSV 
upload CSV with 5 valid emails 5 invitations sent, 
success report 
5 invitations 
sent Pass 
Functional Testing 12: Skip Onboarding Steps 
Testing Objective: To verify skip functionality and reminder system. 
Table 73: Functional Testing for Skip Functionality 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Click Skip for Now On Step 3 of 
onboarding 
Progress saved, 
reminder scheduled 
Skipped 
successfully Pass 
2 Resume skipped 
onboarding 
Click Complete 
Onboarding CTA 
Resume from last 
step 
Resumed 
correctly Pass 
5.2.5 Portfolio Builder Interface 
Functional Testing 13: Create New Portfolio 
Testing Objective: To verify portfolio creation functionality. 
UI Reference: Figure 104-110: User Interface of Portfolio Builder 
Table 74: Functional Testing for Portfolio Creation 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Create portfolio with all 
fields 
Name: "Web Dev 
Portfolio", Tagline: 
"Modern Solutions" 
Portfolio created 
with unique ID 
Portfolio 
created Pass 
2 Create portfolio without 
name Name: "" Error: "Portfolio 
name required" Error displayed Pass 
Functional Testing 14: Add Project to Portfolio 
Testing Objective: To verify project addition functionality. 
196 
 
Table 75: Functional Testing for Adding Projects 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Add project with valid 
data 
Title: "E-commerce 
Site", Description: "Full
stack project" 
Project added to 
portfolio Project added Pass 
2 Upload project images 3 images (PNG, JPG) Images uploaded 
and displayed 
Images 
uploaded Pass 
3 Upload invalid file type File: document.pdf Error: "Only images 
allowed" Error displayed Pass 
Functional Testing 15: Add Testimonials 
Testing Objective: To verify testimonial addition and import. 
Table 76: Functional Testing for Testimonials 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Add manual 
testimonial 
Client: "Jane Smith", 
Content: "Great work!" Testimonial added Testimonial 
added Pass 
2 Import from LinkedIn LinkedIn 
recommendations 
Testimonials 
imported 
Import 
successful Pass 
Functional Testing 16: Portfolio Publishing 
Testing Objective: To verify portfolio preview and publishing. 
Table 77: Functional Testing for Portfolio Publishing 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Preview portfolio Click Preview button Portfolio preview 
displayed Preview shown Pass 
2 Publish portfolio Click Publish button Public URL 
generated URL generated Pass 
3 Download as PDF Click Export PDF PDF downloaded PDF 
downloaded Pass 
5.2.6  Dashboard Interface 
Functional Testing 17: Dashboard Loading 
Testing Objective: To verify dashboard loads with correct data. 
UI Reference: Figure 111: User Interface of Dashboard 
197 
 
Table 78: Functional Testing for Dashboard Loading 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Load dashboard for 
verified user 
User: verified, role: 
"Business Owner" 
Dashboard loads 
with KPIs 
Dashboard 
loaded Pass 
2 Load dashboard for 
unverified user 
User: 
emailVerified=false 
Redirect to 
verification page 
Redirected 
correctly Pass 
Functional Testing 18: Dashboard KPI Display 
Testing Objective: To verify KPI cards display correct data. 
Table 79: Functional Testing for KPI Display 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Display total leads 
count User has 50 leads KPI shows 50 leads Correct count 
shown Pass 
2 Display campaign 
metrics Active campaigns: 3 KPI shows 3 
campaigns 
Correct count 
shown Pass 
3 Refresh dashboard data Click refresh icon Data refreshes, 
timestamp updates Data refreshed Pass 
5.2.7 LinkedIn Sync Interface 
Functional Testing 19: Extension Installation 
Testing Objective: To verify Chrome extension installation flow. 
UI Reference: Figure 112-114: User Interface of LinkedIn Sync 
Table 80: Functional Testing for Extension Installation 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Click Install Extension Chrome browser Redirect to Chrome 
Web Store 
Redirected 
successfully Pass 
2 Extension installed 
detection Extension installed UI updates to show 
Connected Status updated Pass 
Functional Testing 20: LinkedIn Account Connection 
Testing Objective: To verify LinkedIn authentication flow. 
Table 81: Functional Testing for LinkedIn Connection 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Authenticate LinkedIn 
account 
Valid LinkedIn 
credentials 
Connection 
established, token 
stored 
Connected 
successfully Pass 
198 
 
No. Test Case Attribute and Value Expected Result Actual Result Result 
2 Sync LinkedIn profile Click Sync Profile Profile data synced 
with timestamp Data synced Pass 
3 Disconnect LinkedIn Click Disconnect 
Connection 
removed, token 
deleted 
Disconnected Pass 
5.2.8 Email Sync Interface 
Functional Testing 21: Email Account Connection 
Testing Objective: To verify email account connection via SMTP/IMAP. 
UI Reference: Figure 115-118: User Interface of Email Sync 
Table 82: Functional Testing for Email Connection 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Connect Gmail 
account OAuth authentication Account connected 
successfully 
Account 
connected Pass 
2 Connect custom 
SMTP 
Host: 
"smtp.company.com", 
Port: 587 
SMTP configuration 
validated 
Configuration 
saved Pass 
3 Invalid SMTP 
credentials Wrong password 
Error: 
"Authentication 
failed" 
Error displayed Pass 
Functional Testing 22: Test Email Functionality 
Testing Objective: To verify test email sending functionality. 
Table 83: Functional Testing for Test Email 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Send test email Recipient: 
"test@example.com" 
Test email sent, 
success message 
Email sent 
successfully Pass 
2 Verify email delivery Check inbox Email received 
within 30 seconds Email received Pass 
Functional Testing 23: Email Account Management 
Testing Objective: To verify email account disconnect and reconnect. 
Table 84: Functional Testing for Email Management 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Disconnect email 
account 
Click Disconnect 
button 
Account removed, 
status updated Disconnected Pass 
199 
 
No. Test Case Attribute and Value Expected Result Actual Result Result 
2 Reconnect email 
account Click Reconnect Re-authentication 
flow starts 
Reconnection 
initiated Pass 
3 View sync status Check connection 
indicator 
Green indicator for 
connected Status correct Pass 
5.2.9 Help & Support Interface 
Functional Testing 24: Help Center Navigation 
Testing Objective: To verify help center navigation and search. 
UI Reference: Figure 119: User Interface of Help & Support 
Table 85: Functional Testing for Help Center 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Navigate to Help 
Center Click Help menu Help Center page 
loads Page loaded Pass 
2 Expand help category Click category section Articles 
expand/collapse 
Section 
expanded Pass 
3 Search for article Query: "email setup" Matching articles 
displayed Results shown Pass 
4 View article details Click article title Full article content 
shown 
Article 
displayed Pass 
Functional Testing 25: Feedback Submission 
Testing Objective: To verify feedback and support ticket submission. 
Table 86: Functional Testing for Feedback Submission 
No. Test Case Attribute and Value Expected Result Actual Result Result 
1 Submit feedback with 
message 
Subject: "Bug Report", 
Message: "Issue 
details..." 
Feedback submitted, 
confirmation shown 
Submitted 
successfully Pass 
2 Submit with file 
attachment 
Screenshot attached 
(PNG) 
File uploaded with 
feedback File attached Pass 
3 Submit empty feedback Message: "" Error: "Message 
required" Error displayed Pass 
 
 
5.3 Business Rules Testing 
Business rules testing uses decision table-based testing technique to test complex business 
logic. The business rules were defined in functional requirements and use cases. Decision tables 
provide a systematic approach where inputs and outputs are provided in tabular form, modeling 
complicated logic with conditions as inputs and actions as outputs. 
5.3.1 Decision Table 1: User Registration Validation 
Business Rule: User registration requires valid email format, strong password (min 8 chars 
with letters and numbers), and matching password confirmation. 
File Reference: lib/auth.ts, pages/signup.tsx 
Table 87: Decision Table for Registration Validation 
Condition 
Rule 1 
Rule 2 
Rule 3 
Valid Email Format 
Yes 
No 
Yes 
Rule 4 
Strong Password 
Yes 
Yes 
Yes 
No 
Passwords Match 
Yes 
Yes 
Yes 
Yes 
Action: Registration 
No 
Success 
Fail 
Fail 
Table 88: Test Cases for Decision Table 1 
No. 
Email 
Password 
Confirm 
Expected 
Fail 
1 user@test.com SecurePass1 
Actual 
Result 
SecurePass1 Registration Success Success 
Pass 
2 
invalid-email 
SecurePass1 
SecurePass1 Invalid Email Error Error shown Pass 
3 user@test.com 
weak 
weak 
Weak Password Error Error shown Pass 
4 user@test.com SecurePass1 
Different1 
Mismatch Error 
5.3.2 Decision Table 2: Onboarding Progress Calculation 
Error shown Pass 
Business Rule: Onboarding progress is calculated based on completed steps. Users must 
complete minimum required fields to access full platform features. 
File Reference: lib/onboarding.ts 
Table 89: Decision Table for Onboarding Progress 
Condition 
Rule 1 
Rule 2 
Rule 3 
Role Selected 
Yes 
Yes 
Yes 
Rule 4 
Company Info Complete 
No 
Yes 
Yes 
No 
Goals Selected (≥2) - 
Yes 
No - - 
200 
Condition 
Rule 1 
Rule 2 
Rule 3 
Action: Progress % 
Rule 4 
100% 
66% 
33% 
Action: Full Access 
0% 
Granted 
Limited 
Limited 
5.3.3 Decision Table 3: Email Sync Status 
Blocked 
Business Rule: Email sync status is determined by connection state, authentication validity, 
and last sync timestamp. 
File Reference: lib/emailSync.ts 
Table 90: Decision Table for Email Sync Status 
Condition 
Rule 1 
Rule 2 
Account Connected 
Yes 
Yes 
Rule 3 
Token Valid 
No 
Yes 
No 
Action: Status 
Connected (Green) - 
Needs Reauth 
(Yellow) 
Action: Sync Enabled 
Yes 
No 
Disconnected (Gray) 
5.4 Integration Testing 
No 
Integration testing verifies that different modules of the system work together correctly. Unlike 
unit testing (which checks isolated functions) and functional testing (which checks features 
from a user's perspective), integration testing focuses on the interfaces, linkages, and data flow 
between modules. 
5.4.1 Integration Testing 1: User Registration → OTP Verification → Login 
Flow 
Testing Objective: To ensure the complete user authentication flow works seamlessly from 
registration to login. 
Modules Involved: User Profiling, Authentication, Email Service, Database 
UI References: Sign-Up Page, Sign-In Page 
Table 91: Integration Testing for Authentication Flow 
No. 
Test Step 
Action 
Expected Result 
Actual Result 
1 
User 
Registration 
Submit signup form with 
email "user@test.com" 
User created, OTP sent 
to email 
Result 
User created, OTP 
sent 
2 Verify OTP in 
DB 
Query OTP table 
OTP hash exists with 
10-min expiry 
Pass 
OTP record found 
Pass 
201 
202 
 
No. Test Step Action Expected Result Actual Result Result 
3 OTP 
Verification 
Submit correct OTP 
code emailVerified set to true Email verified Pass 
4 Login with 
credentials Submit login form JWT tokens created, 
session started Login successful Pass 
5 Access 
Dashboard Navigate to dashboard Dashboard loads with 
user data Dashboard accessed Pass 
Overall Result: Pass - Complete authentication flow works correctly with proper data flow 
between modules 
5.4.2 Integration Testing 2: Onboarding → Profile Setup → Dashboard 
Access 
Testing Objective: To verify onboarding completion enables full dashboard access. 
Modules Involved: User Profiling, Onboarding, VIBE Command Center 
UI References: Onboarding Screens, Dashboard 
Table 92: Integration Testing for Onboarding Flow 
No. Test Step Action Expected Result Actual Result Result 
1 Select Role Select "Business 
Owner" role 
Role saved, progress 
17% Role saved Pass 
2 Enter 
Company Info 
Fill company name and 
details 
Company info saved, 
progress 50% Info saved Pass 
3 Select Goals Select 3 business goals Goals saved, progress 
83% Goals saved Pass 
4 Complete 
Onboarding Click "Finish" button Onboarding complete, 
redirect to dashboard 
Completed 
successfully Pass 
5 Verify Full 
Access 
Check dashboard 
features All features unlocked Full access granted Pass 
Overall Result: Pass - Onboarding completion correctly enables full platform access 
5.4.3 Integration Testing 3: Portfolio Creation → Preview → Publishing 
Testing Objective: To verify portfolio creation and publishing workflow. 
Modules Involved: Portfolio Builder, Media Storage, URL Generation 
UI References: Portfolio Builder Screens 
203 
 
Table 93: Integration Testing for Portfolio Flow 
No. Test Step Action Expected Result Actual Result Result 
1 Create 
Portfolio 
Enter portfolio name 
and description 
Portfolio created with 
unique ID Portfolio created Pass 
2 Add Projects Add 2 projects with 
images 
Projects saved with 
image URLs Projects added Pass 
3 Add 
Testimonials Add client testimonial Testimonial saved to 
portfolio Testimonial added Pass 
4 Preview 
Portfolio Click Preview button Preview displays all 
content Preview correct Pass 
5 Publish 
Portfolio Click Publish button Public URL generated, 
portfolio live 
Published 
successfully Pass 
6 Access Public 
URL 
Open public URL in 
browser 
Portfolio displays 
correctly Accessible publicly Pass 
Overall Result: Pass - Portfolio creation and publishing workflow functions correctly 
5.4.4 Integration Testing 4: LinkedIn Sync → Profile Data → Lead 
Extraction 
Testing Objective: To verify LinkedIn connection enables profile sync and lead extraction. 
Modules Involved: LinkedIn Sync Extension, Profile Analysis, Prospecting Engine 
UI References: LinkedIn Sync Screens 
Table 94: Integration Testing for LinkedIn Sync Flow 
No. Test Step Action Expected Result Actual Result Result 
1 Install 
Extension 
Install Chrome 
extension 
Extension installed, 
icon appears Extension installed Pass 
2 Authenticate 
LinkedIn 
Connect LinkedIn 
account 
OAuth token stored 
securely Account connected Pass 
3 Sync Profile Click Sync Profile 
button 
Profile data imported to 
VIBE Profile synced Pass 
4 Verify Data in 
DB 
Query LinkedIn 
connection table 
Profile data stored with 
timestamp 
Data stored 
correctly Pass 
5 Enable 
Prospecting 
Access Prospecting 
Engine 
LinkedIn filters 
available Features enabled Pass 
Overall Result: Pass - LinkedIn integration works correctly with data flowing between 
modules 
5.4.5 Integration Testing 5: Email Sync → Account Connection → Test Email 
Testing Objective: To verify email account connection enables outreach functionality. 
Modules Involved: Email Sync, SMTP/IMAP Configuration, Campaign Module 
UI References: Email Sync Screens 
Table 95: Integration Testing for Email Sync Flow 
No. 
Test Step 
Action 
Expected Result 
Actual Result 
1 Connect Email Authenticate Gmail via 
OAuth 
Account connected, 
token stored 
Result 
Account connected 
2 
Verify 
Connection 
Check connection status 
indicator 
Green indicator shown 
Pass 
Status correct 
3 
Send Test 
Email 
Click Send Test button 
Test email sent 
successfully 
Pass 
Email sent 
4 
Verify 
Delivery 
Check recipient inbox Email received within 
Pass 
30 seconds 
5 
Enable 
Campaigns 
Access Campaign 
module 
Email account available 
for selection 
Email received 
Pass 
Account available 
Overall Result: Pass - Email sync integration works correctly enabling campaign 
functionality 