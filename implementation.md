4 Chapter 4: Implementation 
This chapter discusses the implementation details of the project. You are not required to insert 
source code here; however, you must document the core module functionalities using 
pseudocode 
where 
applicable. 
Note: You are required to follow proper coding standards to write your source code. For 
guidelines, General Coding Standards & Guidelines are provided in Appendix D. 
In addition to pseudocode and UI/API documentation, if your implementation includes any 
techniques from Artificial Intelligence (AI), Machine Learning (ML), Deep Learning (DL), Data 
Science, or Cyber security, you must also include the following details wherever applicable: 
• The specific technique/model/algorithm applied (e.g., Decision Trees, CNNs, 
Autoencoders, Encryption Algorithms). 
• The dataset used (source, size, format, any preprocessing applied). 
• Training procedure and evaluation methodology. 
• Achieved metrics (accuracy, precision, recall, F1-score, confusion matrix, etc.). 
• Explanation of how the implementation meets or supports the project’s objectives. 
4.1 Project Methodology & Algorithms 
This section explains the methodology (step-by-step approach) and the core algorithms that 
power the system. Students should avoid trivial operations (e.g., login, logout, simple CRUD) 
and instead focus on the methods and algorithms that: 
• Enforce business rules 
• Perform optimization or scheduling 
• Implement intelligent features such as prediction, classification, or recommendation 
4.1.1 Project Methodology (Step-by-Step Approach) 
The methodology describes the overall approach taken to implement the system. Students 
must clearly describe each stage of their implementation pipeline, including what was done, 
how it was done, and why it was necessary. 
Template: 
1. Data Collection 
o What: Describe the type of data collected (e.g., logs, sensor data, datasets). 
o How: Mention the source (e.g., CICIDS dataset, IoT sensors, API). 
o Why: Explain why this data is important for the project. 
2. Data Preprocessing 
o Missing Values: Explain how you handled them (e.g., mean substitution, forward 
fill). 
o Duplicates: Describe how duplicates were removed (e.g., unique IDs, 
timestamps). 
15 
o Normalization: Mention scaling technique if used (e.g., Min-Max scaling, 
standardization). 
3. Feature Extraction & Selection 
o What: List the key features used (e.g., packet size, user review keywords, image 
attributes). 
o How: Explain how features were extracted and irrelevant ones removed (e.g., 
correlation filtering, PCA). 
4. Model Training 
o Algorithm(s): State the machine learning or AI models used (e.g., Random Forest, 
CNN, LSTM). 
o Training: Mention dataset split (train/test) and evaluation method. 
o Why: Explain why this model was chosen for the problem. 
5. Advanced Techniques (if applicable) 
o NLP: If analyzing text (e.g., logs, reviews), describe tokenization, sentiment 
analysis, etc. 
o Blockchain: If securing data, explain how transactions are stored immutably. 
o Computer Vision: If using images, mention detection or classification methods. 
6. Deployment 
o What: Describe the final system (web app, dashboard, mobile app). 
o How: Mention deployment platform (e.g., cloud, server). 
o Why: State the value of real-time access or monitoring. 
Example:  
Project Methodology 
The implementation of the Cybersecurity Threat Detection System followed the steps below: 
1. Data Collection 
o Network traffic data was gathered from firewall logs and intrusion detection 
systems. 
o Public cybersecurity datasets such as CICIDS and UNSW-NB15 were used to 
train and test the model. 
2. Data Preprocessing 
o Missing values were filled using forward filling or average substitution. 
o Duplicates were identified using session IDs and removed. 
o Data was normalized using Min-Max scaling to prepare it for machine learning 
algorithms. 
3. Feature Extraction & Selection 
o Key features such as packet size, protocol type, and connection duration were 
extracted. 
o Highly correlated or redundant features were removed using correlation analysis 
to reduce noise. 
4. Machine Learning Model Training 
o Random Forest and Deep Neural Networks were trained to classify traffic into 
normal or attack. 
o Models were evaluated using accuracy, precision, recall, and F1-score. 
16 
5. NLP-Based Log Analysis 
o Security logs were processed with tokenization and keyword extraction. 
o Suspicious activities (e.g., repeated login failures) were detected through pattern 
recognition. 
6. Blockchain-Based Security 
o Detected attack records and alerts were logged in a blockchain ledger. 
o This ensured that all events were tamper-proof and auditable. 
7. Deployment & Monitoring 
o The trained models were deployed on a cloud platform. 
o A real-time dashboard displayed alerts, anomalies, and system health for 
administrators. 
4.1.2 Algorithm  
This section documents the major algorithms that power the system. Students should avoid 
trivial operations such as login, logout, or simple CRUD actions. Instead, they should describe 
algorithms that: 
• Enforce business rules 
• Perform optimization or scheduling 
• Implement intelligent features such as prediction, classification, or recommendation 
Each algorithm must include its name, input, output, and pseudocode steps. Following are some 
examples of documenting algorithms in pseudocode format. 
Table 4.1: Examples of Algorithms 
Algorithm Name 
DiscountCalculation 
(Business Rule) 
Details 
Input: OrderAmount  
Output: FinalPrice  
Pseudocode:  
1: procedure DiscountCalculation(OrderAmount)  
2:   Discount ← 0  
3:   if OrderAmount ≥ 5000 then Discount ← 0.20  
4:   else if OrderAmount ≥ 2000 then Discount ← 0.10  
5:   else Discount ← 0.0  
6:   FinalPrice ← OrderAmount – (OrderAmount * Discount)  
7:   return FinalPrice  
8: end procedure 
AppointmentScheduling 
(Optimization) 
Input: DoctorSchedule, PatientPreferredSlot  
Output: ConfirmedAppointment or “Slot Unavailable”  
Pseudocode:  
1: procedure AppointmentScheduling(DoctorSchedule, 
PatientPreferredSlot)  
2:   for each Slot in DoctorSchedule do  
3:     
if Slot == PatientPreferredSlot AND Slot is Available then  
4:       
5:       
ConfirmedAppointment ← Book(Patient, Slot)  
return ConfirmedAppointment  
17 
6:     
end if  
7:   end for  
8:   return "Slot Unavailable"  
9: end procedure 
SentimentPrediction 
(AI/Data Science) 
Input: TrainedModel, InputText  
Output: Sentiment (Positive/Negative)  
Pseudocode:  
1: procedure SentimentPrediction(Model, Text)  
2:   CleanedText ← preprocess(Text)  
3:   Features ← vectorize(CleanedText)  
4:   Prediction ← Model.predict(Features)  
5:   if Prediction ≥ 0.5 then return “Positive”  
6:   else return “Negative”  
7: end procedure 
4.1.3 Guideline for Students 
• Document 1–3 algorithms depending on your project. 
• Use pseudocode instead of actual programming code. 
• Select algorithms that represent core rules, optimization, or intelligent logic in the 
system. 
4.2 Training Results & Model Evaluation (Mandatory for AI/ML/Data 
Science Projects) 
• Describe: 
o Dataset used (name, source, pre-processing) 
o Training setup (platform, GPU/CPU, batch size, epochs) 
o Performance metrics 
o Screenshots of graphs (loss, accuracy, confusion matrix, ROC if applicable) 
4.3 Security Techniques (if applicable) 
• Describe techniques used for: 
o Authentication (JWT, OAuth) 
o Encryption (AES, RSA) 
o Attack prevention (XSS, SQLi handling) 
• If using a model for intrusion detection or anomaly detection, explain its results. 
4.4 External APIs/SDKs 
Describe the third-party APIs/SDKs used in the project implementation in the following table. 
Few examples of APIs are provided in the table. 
18 
Table 4.2 Details of APIs used in the project 
Name of API 
and version 
Description of API Purpose of usage 
List down the API 
endpoint/function/class in which 
it is used 
Stripe (version 
2020-08-27) 
Credit Card 
payment 
integration 
Sandbox used for the 
orders payment  
stripe.paymentMethods.create 
Cloudinary 
Image and Video 
m