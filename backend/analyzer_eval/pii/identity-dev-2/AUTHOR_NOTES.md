# identity-dev-2 labelling notes

All names, CNICs, phones, IBAN, emails and addresses are invented. Ids are per document (p1 in d2-01 has nothing to do with p1 in d2-02).

## Labelling choices
- Honorifics stay outside NAME marks: Mr, Mrs, Ms, Mst, Dr, Prof. Dr., Ch, Syeda, Haji, Mian, Engr, Advocate, Late, Inspector, Oath Commissioner. The Roman-Urdu suffix "sahib" (d2-17, d2-21) is also left outside.
- Initials that belong to the name are inside the mark ("M. U. Tariq", "N. A. Shah", "O. F. Malik", "G. M. Chaudhry", "K. Raza", "A. Noor", "S. Akhtar").
- Short forms (first name only, surname only) get the same id as the full name when only one person in the document could be meant: "Nauman"/"Shah" (d2-06), "Siddiqui" (d2-06), "Kashif"/"Raza" (d2-14), "Sheikh"/"Adnan" (d2-19), "Ghaffar" (d2-21), "Fatima"/"Ambreen" (d2-12), "Riaz" (d2-13), "Saeed" (d2-27). I avoided a bare surname anywhere two people share that surname.
- Role references ("the Landlord", "the Tenant", "the Owner", "the Recipient", "the Managing Director") and job titles under signatures ("Head of Human Resources", "Finance Manager", "Lambardar") are NOT marked at all. NOT marks are used only for business/shop/firm names that contain or look like a person's name: Bilal Traders, Haji Bashir & Sons, Afridi Mobile Centre, G. M. Chaudhry & Co., Hafiz Nadeem Sweets, Babu Electronics, Iqbal & Brothers Engineering. Company names with no personal name (Bright Loom (Pvt.) Ltd, Studio Rang Mahal, Crescent Packaging (Pvt.) Ltd) are unmarked.
- Names inside addresses (Rahim Bakhsh Market, Zaman Khan Street, Gul Rehman Colony, Barkat Ali Road, Bashir Ahmed Town) are NAME marks nested in ADDRESS, each with its own new id; they are never merged with a party, even when spelled the same as one (d2-24: "Bashir Ahmed" the employee = p1, "Bashir Ahmed Town" = p3; d2-10: street "Zaman Khan" = p3, tenant "Zaman Khan Afridi" = p2).
- A firm name is NOT even when it is built from a party's own initials or name (d2-13 "G. M. Chaudhry & Co." is NOT, while "G. M. Chaudhry" on the cc line is NAME p1; d2-04 "Bilal Traders" is NOT).
- OCR variants carry the gold id of the person they garble: Kash1f Raza / Kashif  Raza (double space) / KASHIF RAZA (d2-05); Abdu1 Majeed, N4sreen Akhtar (d2-11); Rizwan U1lah Khan, Mehw1sh Tahir, Mehwish  Tahir (d2-18); Shahid lqbal (lower-case L), Shah1d Iqbal, Tahira Yasrneen (rn for m) (d2-25).
- Line-break splits: "Sana\nMalik" (d2-05), "Abdul\nMajeed" and "Shoaib Ahmed\nMalik" (d2-11), "Rizwan Ullah\nKhan" (d2-18); the whole span including the line break is inside one mark.
- DEADLINE marks cover the full phrase that must survive unchanged ("within 30 days", "on or before the 5th of each month", "two months' notice", "after eleven months", "before 31st December 2025"). Plain event dates (date of agreement, date of death) and amounts are not marked but are left verbatim next to names.
- "parties" lists the people who sign or are bound by the document; witnesses, fathers, deceased persons, advocates and people named in addresses are not listed as parties. In d2-08 only the applicant grandson (p2) is a party; in d2-26 the four living heirs are parties.

## Cases where I was unsure / deliberate judgement calls
- d2-03: "Akhtar Hussain" appears as father of both witnesses. Same spelling alone does not prove identity, so I added "(real brother of Witness 1)" to the text, and only then gave both the same id p5. Imran Akhtar (husband) and Kamran Akhtar (brother-in-law) are plausibly brothers but the text never says whose son Imran is, so Imran has no father mark.
- d2-08: grandfather (Ch. Muhammad Aslam, later "Late Muhammad Aslam") = p1; grandson (applicant) = p2. The resolution rests on "Late" and on "the applicant"; the mention "Late [[p1]]" is p1 because the grandson is alive.
- d2-12: "Dr. Fatima" refers to Dr. Ambreen Fatima (p3); no other Fatima is in the document. Witness "Arif Mehmood" (cousin) is a separate person p6 despite sharing the surname of the Owners and of their father Mehmood Ahmed.
- d2-15: two "Muhammad Ali" (p1 deponent, p2 accused in FIR) distinguished only by father's name and CNIC; "Asghar Ali", "Sher Ali", "Liaquat Ali" share the surname but are four separate ids.
- d2-16: "Arshad Butt" (husband, p2) and "Arshad Mehmood Butt" (witness, p4) are different people; text says so explicitly. Yaqoob Butt is the same person (p5) in the tenant's and in Witness 2's parentage because the text says Witness 2 is the tenant's sister.
- d2-21: "Haji Ghaffar" and "Ghaffar sahib" are taken as the landlord Haji Abdul Ghaffar (p1); there is no other Ghaffar.
- d2-25: the table witness "Shahid Iqbal Bhatti" (p3) is NOT the lessor "SHAHID IQBAL" (p1); the OCR variants in clauses 1 and 2 are assigned to the lessor because they are the payee/rent-raiser, i.e. the Lessor role. A reader relying only on spelling could not decide this.
- d2-26: Witness 1's father "Rafiq Ahmed" (p7) is a different person from the deceased "Late Rafiq Ahmed" (p1); the text states this.
- d2-27: "Respected Dr. Saeed" = Prof. Dr. Saeed Akhtar (p1).
- d2-28: Witness "Danish Akbar" is stated to be unrelated to Rehan Akbar; "Huma Nawaz" is stated to be the Employee's sister. Both are separate ids from the parties.
- Two documents use features "roman_urdu" (d2-17 "thara", "sahib"; d2-21 "Kiraya Nama", "sahib", "Gawah"). No Urdu script is used.

## Helper
check.py (in this folder) validates the file: ASCII/LF/no tabs, YAML parses, allowed kinds/features/types, marks balanced, only NAME nested inside ADDRESS, every party id has a NAME mark. It needs PyYAML; I installed it temporarily into a local _lib folder inside this directory and deleted it afterwards.
