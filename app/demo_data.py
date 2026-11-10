"""Synthetic demo inbox (~120 emails) with matching 'ground-truth' analyses.

Dates are generated relative to *now* every time, so deadlines always look fresh.
The precomputed analyses let you demo the whole app instantly without spending any Gemini quota;
you can also load only the raw emails and let Gemini analyse them for real.
"""
import random
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from .email_client import normalize_subject

DOMAIN_EDU = "campus-demo.edu"


def build_dataset(now: Optional[datetime] = None, seed: int = 7) -> list[dict]:
    """Returns [{'email': {...}, 'analysis': {...}}] sorted oldest -> newest."""
    rnd = random.Random(seed)
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    today = now.date()
    items: list[dict] = []

    # ───────── helpers ─────────
    def due(k: int) -> str:
        return (today + timedelta(days=k)).isoformat()

    def day_str(k: int) -> str:
        d = today + timedelta(days=k)
        return "today" if k == 0 else "tomorrow" if k == 1 else d.strftime("%A, %d %b")

    def rel(k: int) -> str:
        if k < 0:
            return f"{abs(k)} day(s) overdue"
        return "today" if k == 0 else "tomorrow" if k == 1 else f"in {k} days"

    def prio(k: int, high_within: int = 2) -> str:
        return "High" if k <= high_within else "Medium"

    def add(name, addr, subject, body, category, priority, reason, summary, action=False,
            deadlines=(), days_ago=None, hour=None):
        days_ago = rnd.randint(0, 6) if days_ago is None else days_ago
        hour = rnd.randint(8, 21) if hour is None else hour
        received = datetime.combine(today - timedelta(days=days_ago), time(hour, rnd.randint(0, 59)), tzinfo=timezone.utc)
        if received > now:
            received = now - timedelta(hours=rnd.randint(1, 5), minutes=rnd.randint(0, 50))
        n = len(items) + 1
        items.append({
            "email": {
                "message_id": f"<demo-{n:03d}@demo.local>",
                "thread_key": normalize_subject(subject),
                "sender_name": name, "sender_email": addr.lower(), "subject": subject,
                "body": body.strip(), "received_at": received.isoformat(), "source": "demo",
            },
            "analysis": {
                "priority": priority, "priority_reason": reason, "category": category, "summary": summary,
                "action_required": action,
                "deadlines": [{"task": t, "due_date": d, "confidence": c} for t, d, c in deadlines],
            },
        })

    # ═════════════════════════ ACADEMIC ═════════════════════════
    courses = [
        ("Data Structures", "Prof. Anita Sharma", "anita.sharma", "trees and graph traversals"),
        ("Database Management Systems", "Dr. Rakesh Verma", "rakesh.verma", "normalization and SQL joins"),
        ("Machine Learning", "Prof. Neha Kulkarni", "neha.kulkarni", "regression and model evaluation"),
        ("Operating Systems", "Dr. Sandeep Joshi", "sandeep.joshi", "process scheduling algorithms"),
        ("Computer Networks", "Prof. Meera Iyer", "meera.iyer", "TCP congestion control"),
        ("Cloud Computing", "Dr. Arvind Menon", "arvind.menon", "AWS EC2, S3 and IAM basics"),
    ]
    assign_k = [1, 3, 2, 6, 8, 4]
    second_k = [5, 2, 3, 0, 7, 1]
    for i, (course, prof, local, topic) in enumerate(courses):
        addr = f"{local}@{DOMAIN_EDU}"
        k = assign_k[i]
        add(prof, addr, f"Assignment {i + 2} submission – {course}",
            f"Dear students,\n\nAssignment {i + 2} for {course} ({topic}) is now live on the LMS. Please upload a single PDF "
            f"with your solutions by 11:59 PM on {day_str(k)}.\n\nLate submissions carry a 20% penalty and plagiarism will be "
            f"reported to the department.\n\nRegards,\n{prof}",
            "Academic", prio(k), f"Sent by your professor; submission due {rel(k)} and late work is penalised.",
            f"{course} Assignment {i + 2} on {topic} must be uploaded as a PDF by 11:59 PM {day_str(k)}; late work loses 20%.",
            True, [(f"Submit {course} Assignment {i + 2}", due(k), "high")], days_ago=rnd.randint(0, 5))
        k2, kind = second_k[i], i % 4
        if kind == 0:
            add(prof, addr, f"{course} lab record – submit signed copy",
                f"Hello everyone,\n\nPlease submit your completed lab record for {course} with all experiments signed by the lab "
                f"in-charge. Records are collected in Room 204 on {day_str(k2)} between 10 AM and 1 PM.\n\n{prof}",
                "Academic", prio(k2), f"Professor requests a physical document; collection is {rel(k2)}.",
                f"Submit the signed {course} lab record in Room 204 on {day_str(k2)} (10 AM-1 PM).", True,
                [(f"Submit {course} lab record", due(k2), "high")])
        elif kind == 1:
            add(prof, addr, f"Surprise quiz announced – {course}",
                f"Dear students,\n\nA 20-minute quiz covering the last two units of {course} will be held {day_str(k2)} at the "
                f"start of the lecture. It carries 10 internal marks. No make-up quiz will be conducted.\n\n{prof}",
                "Academic", prio(k2), f"Graded quiz {rel(k2)} with no make-up, announced by your professor.",
                f"A 10-mark {course} quiz on the last two units is on {day_str(k2)} at the start of the lecture; no make-up.",
                True, [(f"Prepare for {course} quiz", due(k2), "high")])
        elif kind == 2:
            add(prof, addr, f"Project review slot – {course}",
                f"Hi team,\n\nYour {course} mini-project review is scheduled for {day_str(k2)} at 3:00 PM in the seminar hall. "
                f"Bring your progress report and be ready for a 10-minute demo.\n\nThanks,\n{prof}",
                "Academic", prio(k2), f"Project review with your professor {rel(k2)}; a demo and report are expected.",
                f"{course} project review on {day_str(k2)} at 3 PM: bring a progress report and a 10-minute demo.", True,
                [(f"{course} project review and demo", due(k2), "high")])
        else:
            add(prof, addr, f"Lecture notes uploaded – {course} Unit {rnd.randint(2, 5)}",
                f"Hi all,\n\nThe slides and reference notes for the latest {course} unit are uploaded on the LMS under 'Resources'. "
                f"No action is needed; this is for revision.\n\n{prof}",
                "Academic", "Low", "Informational notes upload from a professor; nothing to do or submit.",
                f"New {course} lecture notes are on the LMS for revision.", False, [])

    exam_k, att_k, schol_k, feed_k, lib_k, noc_k = 4, 2, 6, 5, 1, 9
    add("Examination Cell", f"exam.cell@{DOMAIN_EDU}", "Mid-semester examination timetable released",
        f"Dear students,\n\nThe mid-semester examination timetable is published. Exams begin on {day_str(exam_k)} at 10:00 AM. "
        f"Carry your ID card and admit card; students without them will not be allowed inside.\n\nExamination Cell",
        "Academic", "High", f"Official exam cell notice; exams start {rel(exam_k)} and an admit card is required.",
        f"Mid-semester exams start {day_str(exam_k)} at 10 AM; ID and admit card are mandatory.", True,
        [("Mid-semester exams begin", due(exam_k), "high")], days_ago=1)
    add("Dr. Kavita Rao (HoD CSE)", f"hod.cse@{DOMAIN_EDU}", "Attendance shortage warning – action required",
        f"Dear student,\n\nYour attendance is currently 71%, below the mandatory 75%. Meet me in my cabin by {day_str(att_k)} "
        f"with a written explanation, otherwise you may be barred from the end-semester exam.\n\nDr. Kavita Rao\nHead of Department",
        "Academic", "High", f"Head of Department warning with exam eligibility at stake; meeting required {rel(att_k)}.",
        f"Attendance is 71% (<75%); meet the HoD by {day_str(att_k)} with an explanation to avoid being barred from exams.", True,
        [("Meet the HoD about attendance shortage", due(att_k), "high")], days_ago=0, hour=9)
    add("Scholarship Office", f"scholarship@{DOMAIN_EDU}", "Merit scholarship renewal form – last date",
        f"Dear student,\n\nFill and submit the merit scholarship renewal form with your latest marksheet to the scholarship office by "
        f"{day_str(schol_k)}. Forms received after the deadline will not be processed this year.\n\nScholarship Office",
        "Academic", prio(schol_k), f"Funding-related form with a hard cut-off {rel(schol_k)}.",
        f"Submit the merit scholarship renewal form with your marksheet by {day_str(schol_k)}.", True,
        [("Submit scholarship renewal form", due(schol_k), "high")], days_ago=3)
    add("Academic Affairs", f"feedback@{DOMAIN_EDU}", "Faculty feedback form – please complete",
        f"Dear student,\n\nPlease complete the anonymous faculty feedback form for all your courses by {day_str(feed_k)}. "
        f"It takes about 5 minutes and is required to download the hall ticket.\n\nAcademic Affairs",
        "Academic", "Medium", f"Required for the hall ticket but not urgent; due {rel(feed_k)}.",
        f"Complete the faculty feedback form by {day_str(feed_k)}; it is required to get the hall ticket.", True,
        [("Complete faculty feedback form", due(feed_k), "high")], days_ago=2)
    add("Central Library", f"library@{DOMAIN_EDU}", "Library book due – return to avoid fine",
        f"Dear member,\n\n'Operating System Concepts' issued to you is due {day_str(lib_k)}. A fine of Rs. 5 per day applies after "
        f"the due date. You can renew it online once if no one has reserved it.\n\nCentral Library",
        "Academic", "Medium", f"Small fine at stake; book is due {rel(lib_k)} and can be renewed online.",
        f"Return or renew 'Operating System Concepts' by {day_str(lib_k)} to avoid a Rs. 5/day fine.", True,
        [("Return or renew library book", due(lib_k), "high")], days_ago=2)
    add("Training & Placement Cell", f"tnp@{DOMAIN_EDU}", "NOC request for off-campus internship – submit documents",
        f"Dear student,\n\nStudents applying for off-campus internships must submit the NOC form signed by the HoD by "
        f"{day_str(noc_k)}. Attach the company offer letter with the form.\n\nTraining & Placement Cell",
        "Academic", "Medium", f"Administrative form needed for an internship; deadline {rel(noc_k)}.",
        f"Submit the HoD-signed NOC form with the offer letter by {day_str(noc_k)}.", True,
        [("Submit internship NOC form", due(noc_k), "high")], days_ago=4)
    add("Student Council", f"council@{DOMAIN_EDU}", "Inter-college hackathon registrations open",
        "Hello coders,\n\nRegistrations for the 24-hour inter-college hackathon are open. Teams of up to four can register on the "
        "event page. Prizes worth Rs. 50,000 and internship opportunities.\n\nStudent Council",
        "Academic", "Low", "Optional campus event invitation; no deadline or required action.",
        "Invitation to register a team for the inter-college hackathon.", False, [], days_ago=5)
    add("Dr. Arvind Menon", f"arvind.menon@{DOMAIN_EDU}", "Guest lecture on cloud careers – optional",
        "Dear students,\n\nAn industry speaker will give a guest lecture on cloud careers this week in the auditorium. Attendance is "
        "optional but recommended for those considering AWS certifications.\n\nDr. Arvind Menon",
        "Academic", "Low", "Optional event; recommended but not required.",
        "Optional guest lecture on cloud careers in the auditorium.", False, [], days_ago=3)
    add("Examination Cell", f"exam.cell@{DOMAIN_EDU}", "Revaluation form for previous semester",
        f"Dear student,\n\nStudents who wish to apply for revaluation can submit the form with the fee receipt by "
        f"{day_str(7)}. Results of revaluation will be declared within 3 weeks.\n\nExamination Cell",
        "Academic", "Medium", "Only relevant if you want revaluation; deadline is a week away.",
        f"Revaluation forms with the fee receipt are accepted until {day_str(7)}.", False,
        [("Submit revaluation form (if needed)", due(7), "high")], days_ago=4)

    # ═════════════════════════ RECRUITMENT ═════════════════════════
    nimbus = ("Priya Nair (Nimbus Labs)", "priya.nair@nimbuslabs-demo.com")
    add(nimbus[0], nimbus[1], "Interview invitation – Software Engineer Intern",
        f"Hi,\n\nThank you for applying to Nimbus Labs. We would like to invite you for a technical interview for the Software "
        f"Engineer Intern role. Please confirm one of these slots by {day_str(-3)}: Thursday 11 AM or Friday 3 PM.\n\nBest,\nPriya Nair\nTalent Acquisition, Nimbus Labs",
        "Recruitment", "High", "Recruiter interview invitation that needs a slot confirmation; high career impact.",
        "Nimbus Labs invites you to a technical interview for the SWE Intern role and asks you to pick a slot.", True,
        [("Confirm interview slot with Nimbus Labs", due(-3), "high")], days_ago=6)
    add(nimbus[0], nimbus[1], "Re: Interview invitation – Software Engineer Intern",
        f"Hi,\n\nThanks for confirming. Your interview is booked for {day_str(2)} at 11:00 AM IST on Google Meet (link in the calendar "
        f"invite). Expect 45 minutes: data structures, one SQL question and a short discussion on your projects.\n\nBest,\nPriya",
        "Recruitment", "High", f"Confirmed interview {rel(2)} with a recruiter; preparation needed.",
        f"Nimbus Labs interview confirmed for {day_str(2)} at 11 AM IST (DSA, SQL, project discussion).", True,
        [("Nimbus Labs technical interview", due(2), "high")], days_ago=3)
    add(nimbus[0], nimbus[1], "Re: Interview invitation – Software Engineer Intern",
        "Hi,\n\nA quick reminder to keep your ID proof handy and join 5 minutes early. Please also share your latest resume and "
        "GitHub link before the interview so the panel can review them.\n\nBest,\nPriya",
        "Recruitment", "High", "Follow-up from the recruiter ahead of an imminent interview; documents requested.",
        "Reminder to join 5 minutes early and send your resume and GitHub link before the Nimbus Labs interview.", True,
        [("Send resume and GitHub link to Nimbus Labs", due(1), "medium")], days_ago=0, hour=10)
    k = 3
    add("Arjun Mehta (Orbit Systems)", "arjun.mehta@orbitsystems-demo.com", "Online assessment link – Orbit Systems campus hiring",
        f"Dear candidate,\n\nYou have been shortlisted for the online assessment (90 minutes: aptitude, coding, SQL). The link is valid "
        f"until 6 PM on {day_str(k)}. Use a laptop with a stable connection; the test cannot be restarted.\n\nHR Team, Orbit Systems",
        "Recruitment", prio(k), f"Recruiter assessment with a link expiring {rel(k)}; one attempt only.",
        f"Complete Orbit Systems' 90-minute online assessment before 6 PM {day_str(k)}; no restarts.", True,
        [("Complete Orbit Systems online assessment", due(k), "high")], days_ago=1)
    k = 4
    add("Sneha Reddy (BrightPath Technologies)", "sneha.reddy@brightpath-demo.com", "Offer letter – Associate Software Engineer",
        f"Dear candidate,\n\nCongratulations! We are delighted to offer you the Associate Software Engineer position at BrightPath "
        f"Technologies. Please review the attached offer letter and send your signed acceptance by {day_str(k)}.\n\nWarm regards,\nSneha Reddy, HR",
        "Recruitment", "High", f"A job offer with a signature deadline {rel(k)}; major decision and time-bound.",
        f"BrightPath Technologies offers you the Associate Software Engineer role; send the signed acceptance by {day_str(k)}.", True,
        [("Sign and return BrightPath offer letter", due(k), "high")], days_ago=0, hour=11)
    add("Training & Placement Cell", f"tnp@{DOMAIN_EDU}", "Kestrel Analytics pre-placement talk and registration",
        f"Dear students,\n\nKestrel Analytics will conduct a pre-placement talk on {day_str(3)} at 4 PM in the auditorium. Eligible "
        f"students (CGPA 7.0+) must register on the placement portal by {day_str(2)}.\n\nTraining & Placement Cell",
        "Recruitment", "Medium", "Placement cell drive for eligible students; registration closes soon.",
        f"Register on the portal by {day_str(2)} for the Kestrel Analytics talk on {day_str(3)} at 4 PM (CGPA 7.0+).", True,
        [("Register for Kestrel Analytics drive", due(2), "high")], days_ago=2)
    add("Training & Placement Cell", f"tnp@{DOMAIN_EDU}", "Document verification for placed students",
        f"Dear student,\n\nCarry original 10th, 12th and semester marksheets and your offer letter for verification on {day_str(1)} "
        f"between 10 AM and 4 PM at the placement cell. Absentees will have offers put on hold.\n\nTraining & Placement Cell",
        "Recruitment", "High", f"Mandatory verification {rel(1)}; offer may be put on hold if missed.",
        f"Bring original marksheets and the offer letter to the placement cell on {day_str(1)} (10 AM-4 PM).", True,
        [("Placement document verification", due(1), "high")], days_ago=1)
    add("Karan Malhotra (Kestrel Analytics)", "karan.m@kestrel-demo.com", "Your application has been shortlisted",
        "Hello,\n\nYour profile has been shortlisted for the Data Analyst Intern role at Kestrel Analytics. Our team will contact you "
        "soon with next steps. In the meantime please update your LinkedIn profile.\n\nRegards,\nKaran",
        "Recruitment", "Medium", "Positive recruiter update but no action or date yet.",
        "Shortlisted for Data Analyst Intern at Kestrel Analytics; next steps to follow.", False, [], days_ago=4)
    add("Lumen Software HR", "careers@lumensoft-demo.com", "Update on your application",
        "Dear candidate,\n\nThank you for your interest in Lumen Software. After careful consideration we will not be moving forward "
        "with your application this time. We will keep your resume for future openings.\n\nHR Team",
        "Recruitment", "Low", "A rejection notice; informational and needs no response.",
        "Lumen Software will not move forward with your application.", False, [], days_ago=5)
    add("JobBoard Alerts", "alerts@jobboard-demo.com", "12 new jobs matching 'Python Developer'",
        "Hi,\n\nHere are today's top picks: Python Developer at Zenith Apps, Backend Intern at CloudNest, Junior Data Engineer at "
        "Quill AI and 9 more. Tap to apply.\n\nTo stop these alerts, unsubscribe in settings.",
        "Recruitment", "Low", "Automated job-board digest; browse at leisure.",
        "Daily digest of 12 Python job listings.", False, [], days_ago=0)
    add("JobBoard Alerts", "alerts@jobboard-demo.com", "5 recruiters viewed your profile this week",
        "Hello,\n\nYour profile got 5 views this week. Complete your profile to get more visibility.\n\nUnsubscribe",
        "Recruitment", "Low", "Automated engagement nudge from a job board.",
        "Five recruiters viewed your profile; the board suggests completing it.", False, [], days_ago=2)
    k = 5
    add("Sneha Reddy (BrightPath Technologies)", "sneha.reddy@brightpath-demo.com", "Joining formalities and background check form",
        f"Hi,\n\nPlease fill in the background verification form and upload your ID proofs by {day_str(k)} so we can process your "
        f"onboarding. Tentative joining date will be shared after this.\n\nSneha Reddy, HR",
        "Recruitment", "Medium", f"Post-offer paperwork due {rel(k)}; needed for onboarding.",
        f"Complete the BrightPath background verification form and upload ID proofs by {day_str(k)}.", True,
        [("Submit BrightPath background verification form", due(k), "high")], days_ago=1)
    add("Arjun Mehta (Orbit Systems)", "arjun.mehta@orbitsystems-demo.com", "Re: Online assessment link – results and next round",
        f"Hi,\n\nYou cleared the online assessment. The technical round is on {day_str(6)}. Please reply with your preferred time "
        f"(morning/afternoon) by {day_str(3)}.\n\nArjun",
        "Recruitment", "Medium", f"Passed a round; needs a preference reply {rel(3)}.",
        f"You cleared Orbit Systems' assessment; tell them your preferred time by {day_str(3)} for the {day_str(6)} technical round.",
        True, [("Reply with preferred interview time (Orbit Systems)", due(3), "high")], days_ago=0, hour=12)
    add("CodeCamp Careers", "events@codecamp-demo.com", "Free resume review webinar this Saturday",
        "Hi,\n\nJoin our free webinar on writing ATS-friendly resumes this Saturday at 5 PM. Seats are limited. Register now!\n\nUnsubscribe",
        "Recruitment", "Low", "Optional promotional webinar invitation.", "Free resume-review webinar invitation for Saturday 5 PM.", False, [], days_ago=3)

    # ═════════════════════════ FINANCE ═════════════════════════
    k = 2
    add("Meridian Bank", "cards@meridianbank-demo.com", "Credit card payment due reminder",
        f"Dear customer,\n\nYour credit card statement of Rs. 8,430 is due on {day_str(k)}. Pay at least the minimum due of Rs. 420 "
        f"to avoid late fees and interest charges.\n\nMeridian Bank",
        "Finance", prio(k), f"Bank payment due {rel(k)} with late fees if missed.",
        f"Credit card bill of Rs. 8,430 (min Rs. 420) is due {day_str(k)}.", True,
        [("Pay credit card bill", due(k), "high")], days_ago=1)
    add("Meridian Bank", "statements@meridianbank-demo.com", "Your monthly account statement is ready",
        "Dear customer,\n\nYour account statement for the last month is ready to view in net banking. No action is required.\n\nMeridian Bank",
        "Finance", "Low", "Routine automated statement notification.", "Monthly bank statement is available in net banking.", False, [], days_ago=4)
    add("Meridian Bank", "alerts@meridianbank-demo.com", "UPI transaction failed – amount debited",
        "Dear customer,\n\nYour UPI transaction of Rs. 650 to QuickBite failed but the amount was debited. It will be auto-reversed within "
        "3-5 working days. If not refunded, raise a dispute from the app.\n\nMeridian Bank",
        "Finance", "Medium", "Money debited on a failed payment; may need a dispute if not reversed.",
        "A failed Rs. 650 UPI payment was debited; expect auto-reversal in 3-5 days or raise a dispute.", False, [], days_ago=2)
    k = 3
    add("Accounts Office", f"accounts@{DOMAIN_EDU}", "Tuition fee instalment reminder",
        f"Dear student,\n\nThe second instalment of tuition fees is due by {day_str(k)}. A late fee of Rs. 100 per day will be charged "
        f"after the due date. Pay via the student portal.\n\nAccounts Office",
        "Finance", prio(k, 3), f"Fee deadline {rel(k)} with a daily late fee.",
        f"Pay the second tuition instalment by {day_str(k)} to avoid Rs. 100/day late fee.", True,
        [("Pay tuition fee instalment", due(k), "high")], days_ago=2)
    k = 6
    add("PrintWorks Studio", "billing@printworks-demo.com", "Invoice #PW-2291 for event banners",
        f"Hello,\n\nPlease find attached invoice #PW-2291 of Rs. 18,500 for the event banners and standees. Payment is due by "
        f"{day_str(k)}. Bank details are in the invoice.\n\nPrintWorks Studio",
        "Finance", "Medium", f"Vendor invoice due {rel(k)}; routine but must be paid.",
        f"PrintWorks Studio invoice #PW-2291 for Rs. 18,500 is due by {day_str(k)}.", True,
        [("Pay PrintWorks invoice #PW-2291", due(k), "high")], days_ago=3)
    add("PrintWorks Studio", "billing@printworks-demo.com", "Final reminder: overdue invoice #PW-2291",
        f"Hello,\n\nThis is our final reminder that invoice #PW-2291 is overdue. Please clear the payment by {day_str(1)} to avoid "
        f"suspension of our services for your next event.\n\nPrintWorks Studio",
        "Finance", "High", f"Firm 'final reminder' tone from a vendor; payment demanded {rel(1)}.",
        f"PrintWorks gives a final reminder to pay overdue invoice #PW-2291 by {day_str(1)} or services will be suspended.", True,
        [("Clear overdue invoice #PW-2291", due(1), "high")], days_ago=0, hour=9)
    add("CloudNest Billing", "billing@cloudnest-demo.com", "Your free-tier credits expire soon",
        f"Hi,\n\nYour free-tier credits for CloudNest expire on {day_str(5)}. After that, running instances will be billed at standard "
        f"rates. Stop unused instances to avoid charges.\n\nCloudNest Billing",
        "Finance", "Medium", f"Possible unexpected charges; credits end {rel(5)}.",
        f"CloudNest free-tier credits end {day_str(5)}; stop unused instances to avoid charges.", True,
        [("Stop unused CloudNest instances", due(5), "high")], days_ago=2)
    add("Meridian Bank", "alerts@meridianbank-demo.com", "Scholarship amount credited to your account",
        "Dear customer,\n\nRs. 25,000 has been credited to your savings account ending 4417. Thank you for banking with us.\n\nMeridian Bank",
        "Finance", "Low", "Informational credit alert; no action needed.", "Rs. 25,000 credited to your savings account.", False, [], days_ago=3)
    add("SafeGuard Insurance", "renewals@safeguard-demo.com", "Health insurance renewal due",
        f"Dear policyholder,\n\nYour health insurance policy expires on {day_str(10)}. Renew before the date to keep continuous cover and "
        f"your no-claim bonus.\n\nSafeGuard Insurance",
        "Finance", "Medium", "Renewal needed to avoid a coverage gap; not urgent for 10 days.",
        f"Renew the health insurance policy before {day_str(10)}.", True,
        [("Renew health insurance", due(10), "high")], days_ago=4)
    add("Streamly", "billing@streamly-demo.com", "Receipt for your subscription payment",
        "Hi,\n\nThanks for your payment of Rs. 199 for your monthly Streamly subscription. This is your receipt.\n\nStreamly Billing",
        "Finance", "Low", "Automated payment receipt, nothing to do.", "Receipt for Rs. 199 Streamly subscription payment.", False, [], days_ago=5)
    add("Meridian Bank", "alerts@meridianbank-demo.com", "Debit card transaction alert",
        "Dear customer,\n\nRs. 1,240 was spent at ShopSphere using your debit card ending 3302. If this was not you, call us immediately.\n\nMeridian Bank",
        "Finance", "Low", "Routine transaction alert; matters only if the purchase was not yours.",
        "Rs. 1,240 debit card spend at ShopSphere.", False, [], days_ago=1)
    add("Meridian Bank", "cards@meridianbank-demo.com", "Your credit limit has been increased",
        "Dear customer,\n\nGood news! Your credit limit has been increased. No action is needed.\n\nMeridian Bank",
        "Finance", "Low", "Informational bank notice.", "Your credit limit was increased.", False, [], days_ago=6)

    # ═════════════════════════ SECURITY ═════════════════════════
    add("CodeHub Security", "security@codehub-demo.com", "New sign-in from a Windows device",
        "Hi,\n\nWe noticed a new sign-in to your CodeHub account from Windows in Pune, India. If this was you, no action is needed. If not, "
        "reset your password immediately and review your active sessions.\n\nCodeHub Security",
        "Security", "Medium", "Security alert that matters only if the sign-in was not you.",
        "New CodeHub sign-in from Windows (Pune); secure the account if it wasn't you.", True, [], days_ago=1)
    add("CloudNest Security", "no-reply@cloudnest-demo.com", "Security alert: access key used from a new location",
        "Hello,\n\nAn access key on your account was used from a new IP address. Review activity in the console and rotate the key if "
        "you do not recognise it.\n\nCloudNest Security",
        "Security", "High", "Possible credential compromise on a cloud account that can incur costs.",
        "A CloudNest access key was used from a new IP; review and rotate it if unfamiliar.", True, [], days_ago=0, hour=8)
    add("Meridian Bank Alerts", "security-update@meridianbank-secure-login.co", "URGENT: Your account will be suspended in 24 hours",
        "Dear customer,\n\nWe detected unusual activity. Verify your account NOW at http://meridianbank-secure-login.co/verify or your "
        "account will be permanently suspended. Enter your card number, PIN and OTP.\n\nSecurity Team",
        "Security", "Low", "Likely phishing: sender domain does not match the bank, urgency pressure, asks for PIN/OTP. Do not click.",
        "Suspicious message demanding card details and OTP to avoid suspension; treat as phishing.", False, [], days_ago=1)
    add("Lucky Draw Team", "winner@claim-prize-now.top", "Congratulations! You won an iPhone",
        "You have been selected as today's lucky winner! Claim your prize in the next 2 hours by paying a small shipping fee at "
        "http://claim-prize-now.top.\n\nLucky Draw Team",
        "Security", "Low", "Classic prize scam: unknown sender, too-good-to-be-true offer, payment request. Do not click.",
        "A fake prize notification asking for a shipping fee; scam.", False, [], days_ago=2)
    add("Streamly Support", "support@streamly-billing-help.net", "Payment declined – update your billing now",
        "Hello,\n\nYour payment was declined. Update billing details here within 12 hours or lose access: http://streamly-billing-help.net/login\n\nSupport",
        "Security", "Low", "Probable phishing: look-alike domain and urgent threat to access.",
        "A look-alike billing page asks you to re-enter payment details; likely phishing.", False, [], days_ago=3)
    add("CodeHub", "no-reply@codehub-demo.com", "Your verification code",
        "Your CodeHub verification code is 482913. It expires in 10 minutes. If you did not request this, ignore this email.",
        "Security", "Low", "Automated one-time code that is already stale.", "One-time verification code email.", False, [], days_ago=4)
    add("CodeHub Security", "security@codehub-demo.com", "Your password was changed",
        "Hi,\n\nThe password for your CodeHub account was changed successfully. If you did not do this, contact support right away.\n\nCodeHub Security",
        "Security", "Medium", "Confirmation of a sensitive change; matters if you did not make it.",
        "CodeHub confirms your password was changed.", False, [], days_ago=5)
    add("Meridian Bank", "alerts@meridianbank-demo.com", "OTP for net banking login",
        "Your OTP for net banking login is 771204. Do not share it with anyone, including bank staff.\n\nMeridian Bank",
        "Security", "Low", "Automated one-time password email.", "One-time password for net banking login.", False, [], days_ago=0)

    # ═════════════════════════ PERSONAL ═════════════════════════
    add("Rohan Gupta", "rohan.gupta@mailbox-demo.com", "Goa trip plan!!",
        f"Bro,\n\nPlanning a Goa trip after exams with the gang (5 of us). Looking at {day_str(15)} to {day_str(19)}. Can you confirm by "
        f"{day_str(5)} so I can book the stay?\n\nRohan",
        "Personal", "Medium", f"Friend needs a yes/no {rel(5)} to book; social but time-bound.",
        f"Rohan plans a 5-person Goa trip {day_str(15)}-{day_str(19)} and wants your confirmation by {day_str(5)}.", True,
        [("Confirm Goa trip with Rohan", due(5), "high")], days_ago=4)
    add("Rohan Gupta", "rohan.gupta@mailbox-demo.com", "Re: Goa trip plan!!",
        f"Bro,\n\nFound a villa near Baga for Rs. 2,400 per head for 4 nights. Need an advance of Rs. 1,000 each by {day_str(4)} to hold it. "
        f"Let me know ASAP!\n\nRohan",
        "Personal", "Medium", f"Friend asks for an advance payment {rel(4)} to hold a booking.",
        f"Rohan found a villa at Rs. 2,400/head and wants a Rs. 1,000 advance by {day_str(4)}.", True,
        [("Pay Rs. 1,000 advance for Goa villa", due(4), "high")], days_ago=1)
    add("Mom", "sunita.family@mailbox-demo.com", "Diwali tickets?",
        f"Beta,\n\nHave you booked your train tickets for Diwali? Bookings open soon and trains fill up quickly. Tell me the date so Papa "
        f"can plan to pick you up. Also eat properly!\n\nMom",
        "Personal", "Medium", "Family message asking about travel plans; flexible but tickets sell out.",
        "Mom asks whether you booked Diwali train tickets and which date you arrive.", True,
        [("Book Diwali train tickets", due(7), "medium")], days_ago=2)
    add("Aditi Verma", "aditi.verma@mailbox-demo.com", "Cousin's wedding invitation – RSVP",
        f"Hi!\n\nYou are cordially invited to my brother's wedding on {day_str(21)} in Bhopal. Please RSVP by {day_str(9)} so we can arrange "
        f"accommodation for out-of-town guests.\n\nAditi",
        "Personal", "Medium", f"Family event needing an RSVP {rel(9)}; not urgent.",
        f"Wedding invitation in Bhopal on {day_str(21)}; RSVP by {day_str(9)}.", True,
        [("RSVP to cousin's wedding", due(9), "high")], days_ago=5)
    add("Neha (classmate)", "neha.classmate@mailbox-demo.com", "Can you share your DBMS notes?",
        "Hey,\n\nI missed the last two DBMS lectures. Could you share your notes when you have time? No rush, but before the mid-sem would be great.\n\nThanks!\nNeha",
        "Personal", "Low", "Casual favour from a classmate with no fixed deadline.",
        "Neha asks for your DBMS notes before mid-sems.", True, [], days_ago=3)
    add("Rohan Gupta", "rohan.gupta@mailbox-demo.com", "Re: Goa trip plan!!",
        "Bro,\n\nEveryone confirmed except you and Kunal. Please reply today, I'm paying the villa advance tonight.\n\nRohan",
        "Personal", "Medium", "Friend is waiting on your reply today before paying.",
        "Rohan needs your confirmation today for the Goa villa booking.", True,
        [("Reply to Rohan about Goa trip", due(0), "high")], days_ago=0, hour=13)
    add("Kunal Shah", "kunal.shah@mailbox-demo.com", "Weekend football?",
        "Hey! A few of us are playing football on Saturday at 6 AM at the college ground. Join us if you're free.\n\nKunal",
        "Personal", "Low", "Casual weekend invitation.", "Kunal invites you to Saturday 6 AM football.", False, [], days_ago=2)
    add("Dad", "dad.family@mailbox-demo.com", "Electricity bill and AC servicing",
        "Beta,\n\nThe electricity bill has been paid. The AC servicing person will come next week. Nothing needed from your side. Call when free.\n\nPapa",
        "Personal", "Low", "Family update; no action required.", "Papa says the bill is paid and AC servicing is next week.", False, [], days_ago=4)
    add("Aditi Verma", "aditi.verma@mailbox-demo.com", "Photos from last weekend",
        "Hi, sharing the photo album from last weekend's get-together. Enjoy!\n\nAditi", "Personal", "Low",
        "Casual photo sharing.", "Aditi shared photos from the weekend get-together.", False, [], days_ago=6)
    add("School Alumni Group", "alumni@mailbox-demo.com", "Alumni meet registration open",
        f"Dear alumnus,\n\nThe annual alumni meet is on {day_str(30)}. Register by {day_str(14)} for early-bird pricing.\n\nAlumni Association",
        "Personal", "Low", "Optional social event with a distant date.", f"Alumni meet registration (early bird by {day_str(14)}).", False,
        [("Register for alumni meet (early bird)", due(14), "medium")], days_ago=5)

    # ═════════════════════════ WORK / INTERNSHIP / CLUB ═════════════════════════
    vik = ("Vikram Singh", "vikram.singh@kestrel-demo.com")
    add(*vik, "Weekly report needed by EOD",
        f"Hi,\n\nPlease share your weekly progress report (completed tasks, blockers, next week's plan) by end of day {day_str(0)}. "
        f"I need it for the client review tomorrow morning.\n\nThanks,\nVikram",
        "Work", "High", "Your internship manager needs a report today for a client review.",
        "Vikram needs your weekly progress report by EOD today for tomorrow's client review.", True,
        [("Send weekly progress report to Vikram", due(0), "high")], days_ago=0, hour=9)
    add(*vik, "Code review requested – PR #42 (analytics API)",
        f"Hi,\n\nCould you review PR #42 for the analytics endpoint? I'd like to merge it by {day_str(2)}. Please check error handling and tests.\n\nVikram",
        "Work", "High", f"Manager needs a review to merge {rel(2)}; blocks the team.",
        f"Review PR #42 (analytics API) so it can be merged by {day_str(2)}; check error handling and tests.", True,
        [("Review PR #42", due(2), "high")], days_ago=1)
    add(*vik, "Sprint planning invite – Monday 10 AM",
        f"Hi team,\n\nSprint planning is on {day_str(4)} at 10 AM on Google Meet. Please add your estimates to the board beforehand.\n\nVikram",
        "Work", "Medium", f"Team meeting {rel(4)} with a small prep step.",
        f"Sprint planning on {day_str(4)} at 10 AM; add estimates beforehand.", True,
        [("Add estimates before sprint planning", due(3), "medium")], days_ago=2)
    add(*vik, "Daily standup notes",
        "Hi all,\n\nNotes from today's standup: deployment is on track, QA found two minor bugs, and the dashboard demo moved to Thursday. No action items.\n\nVikram",
        "Work", "Low", "Informational standup notes; no action.", "Standup recap: deployment on track, two minor bugs, demo moved to Thursday.", False, [], days_ago=1)
    add(*vik, "Staging environment access granted",
        "Hi,\n\nYou now have access to the staging environment. Credentials are in the password manager. Let me know if anything doesn't work.\n\nVikram",
        "Work", "Low", "Access confirmation; no action unless it fails.", "Staging environment access has been granted.", False, [], days_ago=4)
    add(*vik, "Quick question about the dashboard metrics",
        f"Hi,\n\nCan you confirm if the churn metric on the dashboard is calculated monthly or weekly? The client asked and I want to reply by {day_str(1)}.\n\nVikram",
        "Work", "Medium", f"Manager needs a factual answer {rel(1)}; short effort.",
        f"Vikram asks if the churn metric is monthly or weekly; he must reply to the client by {day_str(1)}.", True,
        [("Confirm churn metric calculation to Vikram", due(1), "medium")], days_ago=0, hour=15)
    bp = ("Harsh Patel (BluePeak Foods)", "harsh.patel@bluepeak-demo.com")
    add(*bp, "Sponsorship proposal – Startup Summit 2026",
        f"Hello,\n\nThank you for the sponsorship deck. BluePeak Foods is interested in the Gold tier (Rs. 75,000). Could you share a "
        f"detailed benefits breakdown and send the MoU draft by {day_str(4)}?\n\nRegards,\nHarsh Patel\nMarketing Head, BluePeak Foods",
        "Work", "Medium", f"Sponsor interested in Gold tier and requests MoU {rel(4)}; strong lead.",
        f"BluePeak Foods wants the Gold tier (Rs. 75,000) and asks for benefits and an MoU draft by {day_str(4)}.", True,
        [("Send BluePeak benefits breakdown and MoU draft", due(4), "high")], days_ago=6)
    add(*bp, "Re: Sponsorship proposal – Startup Summit 2026",
        f"Hello,\n\nOur finance team approved the Gold tier subject to our logo appearing on the main stage banner. Please confirm the logo "
        f"placement and send the invoice by {day_str(2)}.\n\nRegards,\nHarsh",
        "Work", "High", f"Sponsor approved funding; invoice and logo confirmation needed {rel(2)}.",
        f"BluePeak approved the Gold tier on condition of a main-stage logo; send the invoice and confirm placement by {day_str(2)}.", True,
        [("Confirm logo placement and send invoice to BluePeak", due(2), "high")], days_ago=3)
    add(*bp, "Re: Sponsorship proposal – Startup Summit 2026",
        f"Hello,\n\nA quick reminder: we need the invoice and logo specifications by {day_str(1)}, as our payment cycle closes that day.\n\nHarsh",
        "Work", "High", f"Sponsor deadline {rel(1)} tied to their payment cycle; money at stake.",
        f"BluePeak reminds you to send the invoice and logo specs by {day_str(1)} before their payment cycle closes.", True,
        [("Send BluePeak invoice and logo specs", due(1), "high")], days_ago=0, hour=14)
    ana = ("Ananya Kapoor (E-Cell)", f"ananya.kapoor@{DOMAIN_EDU}")
    add(*ana, "Speaker confirmation needed",
        f"Hi,\n\nWe need the keynote speaker's confirmation by {day_str(1)} so the posters can go to print. Can you follow up with them today?\n\nAnanya",
        "Work", "High", f"Event blocker: posters wait on confirmation {rel(1)}.",
        f"Follow up with the keynote speaker; confirmation is needed by {day_str(1)} for printing posters.", True,
        [("Get keynote speaker confirmation", due(1), "high")], days_ago=0, hour=11)
    add(*ana, "Sponsorship deck review by Friday",
        f"Hi,\n\nPlease review the updated sponsorship deck and share edits by {day_str(5)}. Focus on the pricing slide and the ROI numbers.\n\nAnanya",
        "Work", "Medium", f"Club task with a deadline {rel(5)}; review only.",
        f"Review the sponsorship deck (pricing, ROI) and share edits by {day_str(5)}.", True,
        [("Review sponsorship deck", due(5), "high")], days_ago=2)
    add(*ana, "Venue booking confirmation – Startup Summit",
        f"Hi team,\n\nThe auditorium is booked for {day_str(12)} from 9 AM to 5 PM. Please share the AV requirements by {day_str(6)}.\n\nAnanya",
        "Work", "Medium", f"Venue confirmed; AV needs due {rel(6)}.",
        f"Auditorium booked for {day_str(12)}, 9-5; send AV requirements by {day_str(6)}.", True,
        [("Share AV requirements for venue", due(6), "high")], days_ago=3)
    add(*ana, "Meeting minutes – core team sync",
        "Hi all,\n\nSharing the minutes of today's core team sync. Decisions: ticket price fixed, volunteers to be assigned next week. No action items for you.\n\nAnanya",
        "Work", "Low", "Meeting minutes for information only.", "Minutes of the core team sync: ticket price fixed, volunteers next week.", False, [], days_ago=1)
    add(*ana, "Volunteer schedule draft",
        f"Hi,\n\nThe draft volunteer schedule is attached. Please share your availability by {day_str(7)} so I can finalise it.\n\nAnanya",
        "Work", "Medium", f"Scheduling input needed {rel(7)}.",
        f"Share your availability for the volunteer schedule by {day_str(7)}.", True,
        [("Share volunteer availability", due(7), "medium")], days_ago=2)
    add("Open Source Weekly", "newsletter@osweekly-demo.com", "Issue #212: This week in open source",
        "Hello,\n\nThis week: new Python release candidates, a trending LLM toolkit and 5 beginner-friendly issues to contribute to.\n\nUnsubscribe anytime.",
        "Work", "Low", "Weekly technical newsletter; read when free.", "Weekly roundup of open-source news.", False, [], days_ago=1)
    add("Nimbus Labs Engineering Blog", "blog@nimbuslabs-demo.com", "How we scaled our search to 10M queries",
        "Hi,\n\nOur engineering blog has a new article on scaling search with caching and sharding. Read it on our blog.\n\nUnsubscribe",
        "Work", "Low", "Marketing blog post; no action.", "Blog post about scaling search to 10M queries.", False, [], days_ago=4)
    add(*vik, "Re: Weekly report needed by EOD",
        "Hi,\n\nThanks for the report. Great job on the API tests! One request: add a short note on the pending bugs for next week.\n\nVikram",
        "Work", "Medium", "Manager feedback with a small follow-up request.",
        "Vikram praised your report and asks for a note on pending bugs.", True, [], days_ago=0, hour=18)

    # ═════════════════════════ PROMOTIONS / NEWSLETTERS ═════════════════════════
    promos = [
        ("QuickBite", "offers@quickbite-demo.com", ["Flat {p}% off on your next order", "Hungry? Free delivery on orders above Rs. {a}"],
         "Hi there,\n\nUse code {c} for flat {p}% off on orders above Rs. {a}. Valid till {w}.\n\nOrder now. Unsubscribe | Terms apply"),
        ("ShopSphere", "deals@shopsphere-demo.com", ["Mega sale: up to {p}% off", "Your cart misses you!"],
         "Hello,\n\nBig savings on electronics and fashion, up to {p}% off. Use {c} at checkout. Sale ends {w}.\n\nUnsubscribe"),
        ("LearnHub", "hello@learnhub-demo.com", ["New course: Generative AI in {a} hours", "{p}% off all courses this weekend"],
         "Hi learner,\n\nJoin thousands of students. Use code {c} for {p}% off any course, valid till {w}.\n\nUnsubscribe"),
        ("TechWeekly", "newsletter@techweekly-demo.com", ["TechWeekly #{a}: AI chips, new phones and more", "This week in tech: top {p} stories"],
         "Hello,\n\nThis week's top stories: new AI accelerator announcements, smartphone launches and a major cloud outage post-mortem.\n\nRead more online. Unsubscribe"),
        ("TravelNest", "promo@travelnest-demo.com", ["Flights from Rs. {a} – book now", "Weekend getaways at {p}% off"],
         "Hi traveller,\n\nExplore deals to Goa, Jaipur and Manali. Use {c} for {p}% off hotels. Offer valid till {w}.\n\nUnsubscribe"),
        ("StyleStreet", "offers@stylestreet-demo.com", ["End of season sale – {p}% off", "New arrivals just for you"],
         "Hey,\n\nRefresh your wardrobe. Flat {p}% off with code {c}. Free returns. Ends {w}.\n\nUnsubscribe"),
        ("FitFuel", "hello@fitfuel-demo.com", ["Your weekly workout plan", "Join our {a}-day fitness challenge"],
         "Hi,\n\nStay on track with our new {a}-day challenge. Premium members get {p}% off supplements with {c}.\n\nUnsubscribe"),
        ("Streamly", "marketing@streamly-demo.com", ["New releases this week on Streamly", "Upgrade to Premium and save {p}%"],
         "Hello,\n\nCheck out this week's new shows and movies. Upgrade with code {c} and save {p}% on annual plans.\n\nUnsubscribe"),
        ("GadgetGrid", "deals@gadgetgrid-demo.com", ["Laptop festival: exchange offers up to Rs. {a}", "Deal of the day: {p}% off earbuds"],
         "Hi,\n\nTop gadgets at unbeatable prices. Use {c} for an extra {p}% off. Hurry, ends {w}.\n\nUnsubscribe"),
        ("CodeCamp Digest", "digest@codecamp-demo.com", ["Weekly digest: 10 Python tips", "Hackathons and bootcamps this month"],
         "Hi coder,\n\nThis week: 10 Python tips, a new SQL cheat sheet and upcoming bootcamps. Use {c} for {p}% off.\n\nUnsubscribe"),
    ]
    for name, addr, subjects, body in promos:
        for j in range(3):
            subj = subjects[j % 2].format(p=rnd.choice([10, 15, 20, 30, 40, 50]), a=rnd.choice([99, 149, 299, 499, 1999, 10, 21]))
            text = body.format(p=rnd.choice([10, 15, 20, 30, 40, 50]), a=rnd.choice([199, 299, 499, 999]),
                               c=rnd.choice(["SAVE20", "WELCOME15", "FEST30", "DEAL50"]), w=day_str(rnd.randint(2, 9)))
            add(name, addr, subj, text, "Promotions", "Low",
                f"Automated marketing email from {name}; no action required and no personal deadline.",
                f"Promotional message from {name}: {subj.rstrip('.')}.", False, [], days_ago=rnd.randint(0, 6))

    items.sort(key=lambda it: it["email"]["received_at"])
    return items
