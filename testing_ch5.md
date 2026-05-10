Chapter 5: Testing and Evaluation 
Once the system has been successfully developed, testing has to be conducted to ensure that the 
system works as intended. This is also to check that the system meets the requirements stated 
earlier. Besides that, system testing will help in finding the errors that may be hidden from the 
user. The testing must be completed before it is deployed for use.  
There are few types of testing which include unit testing, functional testing and integration 
testing.  
You are required to perform each of these in-depth to ensure system quality. 
5.1 Unit Testing 
Unit testing verifies the smallest testable components of the software (e.g., individual 
functions, methods, or classes) in isolation. The purpose is to ensure that each unit performs as 
expected, independent of the full system. 
At the FYP level: 
• Software Engineering students may demonstrate automated unit tests using JUnit, 
PyTest, or similar frameworks. 
• Other programs (CS, AI, Cybersecurity, Data Science) may show simplified unit
level tests where functions or algorithms are executed with inputs and outputs compared 
against the expected results. 
Unit Testing 1:  validateEmail() function with valid and invalid credentials 
Testing Objective: To ensure the email validation function works correctly with valid and 
invalid inputs. 
No. Test case/Test script 
Attribute 
and 
Value 
1 
Call validateEmail() 
with valid email 
"abc@gmail.com" 
Expected Result 
Actual Result 
Validates as 
correct email 
(True) 
2 
Call validateEmail() 
with invalid email 
"abc.gmail.com" 
True 
Rejects input and 
returns False 
3 
Call validateEmail() 
with empty string 
"" 
False 
Rejects input and 
returns False 
5.2 Functional Testing 
False 
Functional testing validates that the system modules work correctly as a whole, ensuring that the 
developed system meets its specifications and requirements. Unlike unit testing, which focuses 
on internal functions, functional testing evaluates user-facing features through the UI or APIs. 
Functional Testing 1: Login with different roles (Management, Patient, Doctor)  
Objective: To ensure that the correct page with the correct navigation bar is loaded.   
22 
No. Test Case 
1 
Login as 
‘Management’ 
Attribute and value Expected Result 
Username: M003, 
Password: 1234 
Actual Result 
Result 
Management 
dashboard with 
navigation bar is 
displayed 
2 
Login as 
‘Doctor’ 
Username: D003, 
Password: 1234 
Redirected to 
Management 
main page 
Pass 
Doctor dashboard 
with navigation 
bar is displayed 
5.3 Business Rules Testing 
Login failed – 
invalid 
credentials error 
Fail 
Decision table based testing technique is used to test business rules. The business rules were 
defined in FRs and Use Cases 
Decision based testing uses a systematic approach where input and outputs are provided in 
tabular form. It is a precise and compact way to model complicated logic. The table contains 
conditions and actions are used for test cases where conditions as inputs and actions as outputs. 
Detailed example is as given in Appendix E. 
5.4 Integration Testing 
Integration testing verifies that different modules of the system work together correctly. Unlike 
unit testing (which checks isolated functions) and functional testing (which checks features from 
a user’s perspective), integration testing focuses on the interfaces, linkages, and data flow 
between modules developed by different team members. 
Since FYPs are team-based, integration testing is essential to ensure that the combined work of 
individual members forms a functioning system. Students must design at least one or two 
integration scenarios to demonstrate how modules interact and exchange data. 
Integration Testing 1:   Scheduling Patient Appointment 
Testing Objective: To ensure the scheduling is being done correctly and the interface between 
module ‘Patient/Doctor Management’ and module ‘Appointment/Scheduling’ is running 
correctly. 
No. Test case/Test script  
Attribute and value  Expected result  
Actual result Result  
1 
Create Appointment 
(Patient ↔ Doctor ↔ 
Scheduler) 
Doctor schedule, 
Patient’s preferred 
Pass 
date/time 
2 
Update Appointment 
(Scheduler ↔ 
Database ↔ 
Select new 
date/time 
Appointment record 
created with correct 
doctor, patient, and 
date/time 
Appointment 
created 
successfully 
Appointment updated 
and linked records 
(database + 
Appointment 
updated 
successfully 
Pass 
23 
Notification) 
notification) reflect