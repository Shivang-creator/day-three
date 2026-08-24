# Rule pack source — postnatal follow-up of mother and newborn after facility birth

Compiled 25 Aug 2026 from published WHO and Government of India documents only. No live patient
data was used; no facility, ASHA, or patient was named. Every rule below is a **verbatim quote**
from one of the sources in the table below — nothing is paraphrased into a rule without the quote
sitting next to it, and nothing that could not be found in a published document was invented (see
"What we do NOT model").

Scrape budget: 15 of 25 scrapes used (Firecrawl `bin/fc` / direct `curl` to the scrape endpoint),
plus ~14 `firecrawl_search` calls to locate the official URLs below.

## Sources

| ID | Document | Publisher / Date | URL |
|---|---|---|---|
| **S1** | WHO recommendations on maternal and newborn care for a positive postnatal experience | WHO, 2022 (ISBN 978-92-4-004598-9) | `https://iris.who.int/server/api/core/bitstreams/73dec697-c033-449c-8323-1cd04a8d8f20/content` (landing page: `https://www.who.int/publications/i/item/9789240045989`) |
| **S2** | Pregnancy, Childbirth, Postpartum and Newborn Care: A guide for essential practice (PCPNC), 3rd edition | WHO / UNFPA / UNICEF, 2015 | `https://iris.who.int/server/api/core/bitstreams/e9f751fd-6eab-42cb-9e0c-0eb86a0365bb/content` (landing page: `https://www.who.int/publications/i/item/9789241549356`) |
| **S3** | Integrated Management of Childhood Illness (IMCI), Distance Learning Course — Module 2: The Sick Young Infant | WHO | `https://iris.who.int/bitstreams/a246c69c-3bf4-4799-b425-065c5778213a/download` |
| **S4** | Guideline: Managing possible serious bacterial infection in young infants when referral is not possible (PSBI) | WHO, 2015 (ISBN 978-92-4-150926-8) | `https://iris.who.int/bitstream/handle/10665/181426/9789241509268_eng.pdf?sequence=1` |
| **S5** | Home Based Newborn Care (HBNC) Operational Guidelines | Ministry of Health and Family Welfare, Govt. of India, 2011 | `https://nhm.gov.in/images/pdf/communitisation/asha/Orders-Guidelines/HBNC_Operational_Guidelines_English.pdf` |
| **S6** | Postnatal Care for Mothers and Newborns: Highlights from the WHO 2013 Guidelines (corroborating brief, quotes the WHO 2010/2013 technical consultation) | WHO-sourced brief published via MCSP/USAID, March 2015 | `https://cdn.who.int/media/docs/default-source/mca-documents/nbh/brief-postnatal-care-for-mothers-and-newborns-highlights-from-the-who-2013-guidelines.pdf` |

S1 is the current (2022) global guideline and is treated as primary for the contact schedule and
the newborn-danger-sign recommendation. S2 (PCPNC) is the WHO field job-aid that translates the
same schedule and danger signs into the two-tier "go immediately / go as soon as possible"
counselling language the routing engine needs. S3 and S4 are the WHO clinical-classification
sources for the newborn symptom screen. S5 is the sole source for the India-specific ASHA
home-visit schedule and the pipeline table. S6 is corroboration only, never a rule's sole source.

---

## SCHED — follow-up contact schedule

| ID | Rule | Applies to | Source |
|---|---|---|---|
| `SCHED-WHO-FACILITY24` | "If birth is in a health facility, healthy women and newborns should receive postnatal care in the facility for at least 24 hours after birth." | facility births | S1, Recommendation on timing of discharge |
| `SCHED-WHO-4CONTACTS` | "If birth is at home, the first postnatal contact should be as early as possible within 24 hours of birth. At least three additional postnatal contacts are recommended for healthy women and newborns, between 48 and 72 hours, between 7 and 14 days, and during week six after birth." *(Recommended)* | mother + newborn, all births | S1 |
| `SCHED-PCPNC-C1` | "First contact: within 24 hours after childbirth." | mother + newborn | S2, "Care for the mother after birth" / "Care for the baby after birth" counselling sheets (M4, M6) |
| `SCHED-PCPNC-C2` | "Second contact: on day 3 (48-72 hours)." | mother + newborn | S2, M4 / M6 |
| `SCHED-PCPNC-C3` | "Third contact: between day 7 and 14 after birth." | mother + newborn | S2, M4 / M6 |
| `SCHED-PCPNC-C4` | "Final postnatal contact (clinic visit): at 6 weeks after birth." | mother + newborn | S2, M4 / M6 |
| `SCHED-PCPNC-C4-IMZ` | "At these visits your baby will be vaccinated. Have your baby immunized." | newborn, week-6 contact | S2, M6 |
| `SCHED-HBNC-INSTITUTIONAL` | "Six visits in the case of institutional delivery (Days 3, 7, 14, 21, 28 and 42)" | India, ASHA home visits, institutional (facility) birth | S5, §2.5(1) |
| `SCHED-HBNC-HOME` | "Seven visits in the case of home delivery (Day 1, 3, 7, 14, 21, 28, and 42)." | India, ASHA home visits, home birth | S5, §2.5(1) |
| `SCHED-HBNC-IEC-INSTITUTIONAL` | "3rd, 7th, 14, 21st, 28 and 42nd day for Institutional deliveries" | India, ASHA home visits, institutional birth (corroborating restatement) | S5, Annexure 3 |
| `SCHED-HBNC-IEC-HOME` | "1st, 3rd, 7th, 14, 21st, 28 and 42nd day for Home deliveries" | India, ASHA home visits, home birth (corroborating restatement) | S5, Annexure 3 |

**Engine implication:** for an India deployment following facility (institutional) birth, `SCHED-HBNC-INSTITUTIONAL` (days 3, 7, 14, 21, 28, 42, all counted from birth) is the operative contact ladder for ASHA home visits, layered on top of the WHO `SCHED-WHO-4CONTACTS` clinic-contact ladder (24h in-facility, day 3, days 7–14, week 6) which is what facility/ANM-side follow-up should target. These are two different, non-identical schedules for two different actors — see "Where the sources disagree."

---

## CHK — what each WHO contact should check (maternal side)

| ID | Rule | Contact | Source |
|---|---|---|---|
| `CHK-MAT-24H-VITALS` | "All postpartum women should have regular assessment of vaginal bleeding, uterine tonus, fundal height, temperature and heart rate (pulse) routinely during the first 24 hours, starting from the first hour after birth. Blood pressure should be measured shortly after birth. If normal, the second blood pressure measurement should be taken within 6 hours. Urine void should be documented within 6 hours." | first 24 hours | S1, Recommendation 1 |
| `CHK-MAT-SUBSEQUENT` | "At each subsequent postnatal contact beyond 24 hours after birth, enquiries should continue to be made about general well-being and assessments made regarding the following: micturition and urinary incontinence, bowel function, healing of any perineal wound, headache, fatigue, back pain, perineal pain and perineal hygiene, breast pain and uterine tenderness and lochia." | every contact beyond 24h | S1 |
| `CHK-MAT-PERINEAL` | "All women should be asked about perineal pain and other perineal conditions (e.g. perineal trauma healing and haemorrhoids) during their postpartum stay in health facilities and at each postnatal care contact. Women should be advised on danger signs and symptoms, including any exacerbation of perineal pain as a manifestation of postpartum complications such as haematomas, haemorrhoids and infection." | every contact | S1 |
| `CHK-NB-DANGERSIGNS` | "The following signs should be assessed during each postnatal care contact, and the newborn should be referred for further evaluation if any of the signs is present: not feeding well; history of convulsions; fast breathing (breathing rate >60 per minute); severe chest in-drawing; no spontaneous movement; fever (temperature >37.5℃); low body temperature (temperature<35.5℃); any jaundice in first 24 hours after birth, or yellow palms and soles at any age." | every contact | S1, Recommendation 25 |
| `CHK-BF-EVERY-CONTACT` | "All babies should be exclusively breastfed from birth until 6 months of age. Mothers should be counselled and provided with support for exclusive breastfeeding at each postnatal contact." | every contact | S1, Recommendation 42 |
| `CHK-CORD-CARE` | "32a. Clean, dry umbilical cord care is recommended." | every contact until cord separates | S1, Recommendation 32a |

---

## NB — newborn symptom screen (routing: routine / urgent-visit / emergency-escalate)

**Emergency-escalate tier**

| ID | Rule | Source |
|---|---|---|
| `NB-EMERG-WHOREC25` | (Same quote as `CHK-NB-DANGERSIGNS`.) "...the newborn should be referred for further evaluation if any of the signs is present: not feeding well; history of convulsions; fast breathing (breathing rate >60 per minute); severe chest in-drawing; no spontaneous movement; fever (temperature >37.5℃); low body temperature (temperature<35.5℃); any jaundice in first 24 hours after birth, or yellow palms and soles at any age. The parents and family should be encouraged to seek health care early if they identify any of the above danger signs between postnatal care visits." *(Recommended)* | S1, Recommendation 25 |
| `NB-EMERG-IMCI-VERYSEVERE` | "Any one of the following signs Not feeding well or Convulsions or Fast breathing (60 breaths per minute or more) or Severe chest indrawing or Fever (37.5°C* or above) or Low body temperature (less than 35.5°C*) or Movement only when stimulated or no movement at all." → classify "Pink: VERY SEVERE DISEASE" → "Give first dose of intramuscular antibiotics, Treat to prevent low blood sugar, Refer URGENTLY to hospital, Advise mother how to keep the infant warm on the way to the hospital." | S3, "How will you classify signs of serious illness in a sick young infant?" |
| `NB-EMERG-PSBI-SEVERE` | "Clinical severe infection: A young infant (0–59 days old) with at least one sign of severe infection (i.e. movement only when stimulated, not feeding well on observation, temperature ≥ 38 °C or < 35.5 °C or severe chest in-drawing)." | S4, definitions |
| `NB-EMERG-PCPNC-COUNSEL` | "Go to hospital or health centre immediately, day or night, DO NOT wait, if your baby has any of the following signs: Difficulty breathing. Fits. Fever (temperature>=37.5 degrees celsius). Hypothermia(<35.5 degrees celsius). Feels cold. Bleeding. Stops feeding. Diarrhoea." | S2, "Care for the baby after birth" (M6) |

**Urgent-visit tier**

| ID | Rule | Source |
|---|---|---|
| `NB-URGENT-IMCI-LOCALINFECTION` | "Umbilicus red or draining pus, Skin pustules" → classify "Yellow: LOCAL BACTERIAL INFECTION" → "Give an appropriate oral antibiotic, Teach the mother to treat local infections at home, Advise mother to give home care for the young infant, Follow up in 2 days." | S3 |
| `NB-URGENT-IMCI-UMBILICUS-DEF` | "The umbilical cord usually separates one to two weeks after birth. The wound heals within 15 days. Redness of the end of the umbilicus, or pus draining from the umbilicus, is a sign of umbilical infection. Recognizing and treating an infected umbilicus early are essential to prevent sepsis." | S3 |
| `NB-URGENT-PCPNC-COUNSEL` | "Go to the health centre as soon as possible if your baby has any of the following signs: Difficulty feeding. Feeds less than every 5 hours. Pus coming from the eyes. Irritated cord with pus or blood. Yellow eyes or skin. Ulcers or thrush (white patches) in the mouth." | S2, M6 |

**Routine tier**: none of the above present → default to the next scheduled `SCHED-*` contact.

---

## MAT — maternal symptom screen (routing: routine / urgent-visit / emergency-escalate)

**Emergency-escalate tier**

| ID | Rule | Source |
|---|---|---|
| `MAT-EMERG-PCPNC` | "Go to hospital or health centre immediately, day or night, DO NOT wait, if any of the following signs: Vaginal bleeding has increased. Fits. Fast or difficult breathing. Fever and too weak to get out of bed. Severe headaches with blurred vision. Calf pain, redness or swelling; shortness of breath or chest pain." | S2, "Care for the mother after birth" (M4) |

**Urgent-visit tier**

| ID | Rule | Source |
|---|---|---|
| `MAT-URGENT-PCPNC` | "Go to health centre as soon as possible if any of the following signs: Swollen, red or tender breasts or nipples. Problems urinating, or leaking. Increased pain or infection in the perineum. Infection in the area of the wound. Smelly vaginal discharge." | S2, M4 |
| `MAT-URGENT-WHOREC-PERINEAL` | (Same quote as `CHK-MAT-PERINEAL`.) "...Women should be advised on danger signs and symptoms, including any exacerbation of perineal pain as a manifestation of postpartum complications such as haematomas, haemorrhoids and infection." | S1 |

**Routine tier**: none of the above present → default to the next scheduled `SCHED-*` contact.

---

## Where the sources disagree

1. **Two different, non-identical schedules for two different actors.** S1/S2 (WHO, clinic-facing)
   specify four contacts: within 24h, day 3 (48–72h), days 7–14, week 6. S5 (India, ASHA home-visit
   programme) specifies six or seven contacts on fixed calendar days: 3, 7, 14, 21, 28, 42 (plus
   day 1 for home births). They overlap at day 3, ~day 7–14, but S5 has no week-6 visit and adds
   days 21 and 28 that S1/S2 do not mention at all. **Resolved:** the engine must run two schedules
   in parallel, not merge them into one — S1/S2 for what a facility/clinic promises, S5 for what an
   ASHA is paid and expected to deliver at home. Do not silently collapse them.

2. **Newborn fever threshold: 37.5°C vs 38°C.** S1 Recommendation 25 and S3 (IMCI "VERY SEVERE
   DISEASE" classification) both use **fever (temperature >37.5°C or 37.5°C or above)** as an
   emergency sign. S4 (PSBI, "clinical severe infection" definition) uses **temperature ≥ 38°C**
   for the same severe-infection concept. **Resolved:** the engine uses the lower, more
   conservative WHO PNC/IMCI threshold (>37.5°C) as the emergency trigger, since S1 is the current
   (2022) primary guideline and S3 is the WHO's own clinical-classification training material for
   the same age group; S4's 38°C threshold is noted in the rule table (`NB-EMERG-PSBI-SEVERE`) but
   not used as the operative cutoff. This is a genuine, unresolved disagreement between two live
   WHO publications, not a typo — flag it in the UI copy if the threshold is ever surfaced to a
   clinician.

3. **"No spontaneous movement" (S1) vs "movement only when stimulated or no movement at all"
   (S3/S4).** S1's Recommendation 25 only lists "no spontaneous movement" as the danger sign; S3
   and S4 both add the intermediate state "movement only when stimulated" as also being an
   emergency sign. **Resolved:** the engine follows S3/S4's more sensitive wording (a two-part
   check: moves on its own vs. moves only when touched/stimulated vs. no movement at all) since
   S1's wording is a shorter summary of the same underlying WHO newborn-danger-sign construct that
   S3/S4 spell out in full for clinical use.

## What we do NOT model

- **Postpartum depression / thoughts of self-harm as a routable maternal danger sign.** None of
  S1, S2, S4, S5, or S6 that were actually read contain a quotable danger-sign line for this (S1's
  index references postpartum depression only as an intervention topic, not as a symptom-screen
  item; the search budget was directed at deadline-critical items per the coordinator's stop
  instruction before this could be tracked to a primary WHO/MoHFW screening tool such as the
  Edinburgh Postnatal Depression Scale). **Do not invent a threshold or a route for this** — until
  a specific published screening rule is sourced, the engine must not claim to detect it.
- **HBYC (Home Based Care for Young Child) day-count schedule.** A PDF was located
  (`https://www.nipi-cure.org/upload/resources/imgddf915_Home-Based-Care-for-Young-Child-HBYC-Operational-Guidelines-2018.pdf`,
  hosted by NIPI, not nhm.gov.in directly) but was never scraped or verified — it is out of scope
  for postnatal (0–42 day) follow-up since HBYC covers ages beyond the newborn period, and time ran
  out before an official nhm.gov.in-hosted copy could be confirmed. Do not cite HBYC day-counts
  until this is verified against an official copy.
- **LaQshya discharge criteria.** The official page (`https://qps.nhsrcindia.org/laqshya`) was
  fetched and confirms LaQshya is MoHFW's real labour-room/immediate-postpartum quality programme,
  but it describes the initiative's objectives, not a quotable discharge-readiness checklist or
  danger-sign list — no rule was extracted from it. Any "ready for discharge" gate in the engine
  needs a different, more specific LaQshya or FBNC (Facility Based Newborn Care) source before it
  can be built.
- **The exact ASHA-facing danger-sign checklist form.** S5 repeatedly references "Checklist for
  first Visit to the Newborn (Annexure 1a)" and "Home visit form (Annexure 1b)" and states the
  ASHA's job includes "Danger signs identification & prompt referral" and "Detect signs and
  symptoms of sepsis, provide first level care and refer the baby to an appropriate center" — but
  the scraped markdown of the PDF did not carry the annexure tables themselves (PDF-to-markdown
  conversion dropped the form content), so the exact sign list ASHA is trained to check is **not**
  independently confirmed from S5 beyond the general "danger sign identification" mandate. The
  engine should use the WHO NB/MAT tables above for the actual symptom screen, not assume they are
  identical to Annexure 1a/1b, which were never read.
- **Mode-of-delivery-specific schedule adjustments** (e.g. a different ladder after caesarean vs.
  vaginal birth). None of the six sources read specify a distinct contact schedule by delivery
  mode; S1's "at least 24 hours" facility-stay recommendation is delivery-mode-agnostic in the text
  actually read. Do not assume a caesarean-specific schedule exists until sourced.

---

## Pipeline — who acts at each contact (India, sourced from S5 only)

| # | Actor | What they do (verbatim) | Fail / escalation mode | Source |
|---|---|---|---|---|
| 1 | **ASHA** (Accredited Social Health Activist) | "Services offered: Essential care of the newborn, examination of the newborn, Early recognition of danger signs, stabilization, and referral, Counseling of mother for Breastfeeding, Warmth, Care of the baby, Immunization, Post Partum Care and use of Family Planning Methods." Conducts the home visits on the `SCHED-HBNC-*` day ladder. | "Detect signs and symptoms of sepsis, provide first level care and refer the baby to an appropriate center." | S5, Annexure 3; §2.3 item 5 |
| 2 | **ANM** (Auxiliary Nurse Midwife) | Named alongside ASHA and Medical Officers as a required "provider of HBNC" who must be "aware of the principles and practice of Home Based Newborn care." Reviews ASHA's home-visit performance: "The ANM should review the performance of all ASHA with respect to home visits for newborns in her sub center area during the VHND/village visit." | Backstop home visit: "If the family is unable to go, the ASHA should ensure that the ANM visits the sick newborn on a priority basis." | S5, §1.8; §2.5(4); §2.3 item 5 |
| 3 | **Medical Officer / PHC** | Named as a required "provider of HBNC" (§1.8). Approves ASHA payments: "Payment to ASHAs should be made by the PHC staff (clerk/accountant... ) after taking approval from the MO/PHC." | Receiving facility for cases the ASHA/ANM refer onward (S5 does not give the MO/PHC a separately quoted clinical action beyond payment approval and general HBNC awareness — this is noted, not inflated). | S5, §1.8; §2.5(5) |
| 4 | **Referral facility (FRU/CHC/DH, unnamed generically in S5)** | Not separately described in S5 beyond "refer the baby to an appropriate center" — S5 does not name which facility tier receives which severity of referral. | — | S5, §2.3 item 5 |

Note: S5's own text is thinner on the ANM/MO/facility side than on the ASHA side — most of the
document is an ASHA training and payment manual. The table above states only what is directly
quotable; it does not infer an ANM or MO clinical protocol that S5 does not spell out.
