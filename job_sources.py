"""
Real-time job data layer.

Priority order:
  1. LIVE  - Remotive public API (no key) and Adzuna (optional keys via env vars).
  2. CACHE - last successful live response, kept for 10 minutes.
  3. SEED - built-in dataset of companies + roles so the product always works.

All endpoints in the app consume jobs in one shape (see _normalize_*).
"""

import os
import time
import threading
import random
from typing import Optional

import requests

from skills import extract_skill_names

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

CACHE_TTL_SECONDS = 600  # 10 minutes
FETCH_TIMEOUT = 15

_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "jobs": []}  # in-process cache


# ---------------------------------------------------------------- normalizers

def _normalize_remotive(j: dict) -> dict:
    desc = j.get("description") or ""
    return {
        "id": f"remotive-{j.get('id')}",
        "title": (j.get("title") or "").strip(),
        "company": (j.get("company_name") or "").strip(),
        "location": j.get("candidate_required_location") or "Remote",
        "url": j.get("url"),
        "type": j.get("job_type") or "full_time",
        "published": (j.get("publication_date") or "")[:10],
        "salary": j.get("salary") or "",
        "tags": j.get("tags") or [],
        "description": desc[:4000],
        "required_skills": extract_skill_names(f"{j.get('title','')} {' '.join(j.get('tags') or [])} {desc[:2500]}"),
        "source": "remotive",
    }


def _normalize_adzuna(j: dict) -> dict:
    desc = j.get("description") or ""
    loc = j.get("location") or {}
    return {
        "id": f"adzuna-{j.get('id')}",
        "title": (j.get("title") or "").strip(),
        "company": ((j.get("company") or {}) or {}).get("display_name", "Unknown"),
        "location": loc.get("display_name", "") if isinstance(loc, dict) else str(loc),
        "url": j.get("redirect_url"),
        "type": "full_time",
        "published": (j.get("created") or "")[:10],
        "salary": "",
        "tags": [],
        "description": desc[:4000],
        "required_skills": extract_skill_names(f"{j.get('title','')} {desc[:2500]}"),
        "source": "adzuna",
    }


# ---------------------------------------------------------------- live fetches

def _fetch_remotive(query: Optional[str], limit: int) -> list[dict]:
    params = {"limit": min(max(limit, 1), 50)}
    if query:
        params["search"] = query
    r = requests.get(REMOTIVE_URL, params=params, timeout=FETCH_TIMEOUT)
    r.raise_for_status()
    jobs = r.json().get("jobs", [])
    return [_normalize_remotive(j) for j in jobs]


def _fetch_adzuna(query: Optional[str], limit: int) -> list[dict]:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []
    params = {"app_id": app_id, "app_key": app_key, "results_per_page": min(limit, 50)}
    if query:
        params["what"] = query
    r = requests.get(ADZUNA_URL.format(country="in", page=1), params=params, timeout=FETCH_TIMEOUT)
    r.raise_for_status()
    return [_normalize_adzuna(j) for j in r.json().get("results", [])]


# ---------------------------------------------------------------- seed fallback

_SEED_COMPANIES = [
    ("Google", ["Python", "Java", "Go", "System Design", "Machine Learning", "Cloud", "Data Structures"], "Search, cloud, and AI products at global scale."),
    ("Microsoft", ["C++", "C#", "Azure", "System Design", "Python", "Testing", "SQL"], "Enterprise cloud, productivity, and AI platform company."),
    ("Amazon", ["Java", "Python", "AWS", "System Design", "Microservices", "SQL", "Docker"], "Global commerce and cloud at massive scale."),
    ("Meta", ["Python", "C++", "JavaScript", "System Design", "Machine Learning", "SQL"], "Social platforms and AI-driven products at internet scale."),
    ("Apple", ["Swift", "Objective-C", "iOS", "Python", "System Design", "Testing"], "Consumer hardware, software, and services ecosystem."),
    ("Netflix", ["Java", "JavaScript", "AWS", "System Design", "Microservices", "Testing"], "Streaming and large-scale media platform operations."),
    ("Uber", ["Go", "Java", "Python", "System Design", "SQL", "Kubernetes"], "Mobility and logistics platform with large distributed systems."),
    ("Airbnb", ["JavaScript", "Python", "React", "Node.js", "AWS", "SQL"], "Marketplace platform for travel and experiences."),
    ("Stripe", ["Python", "JavaScript", "SQL", "System Design", "REST APIs", "Testing"], "Payment infrastructure and developer-first financial products."),
    ("Atlassian", ["JavaScript", "TypeScript", "React", "Node.js", "AWS", "Testing"], "Developer tooling and collaboration SaaS."),
    ("GitHub", ["Ruby", "JavaScript", "Go", "Testing", "Git", "REST APIs"], "Developer platform and source code collaboration."),
    ("GitLab", ["Ruby", "Go", "JavaScript", "Linux", "Testing", "Docker"], "DevSecOps platform and CI/CD software."),
    ("Adobe", ["JavaScript", "Python", "React", "SQL", "Machine Learning", "Testing"], "Creative software and digital media platform."),
    ("Salesforce", ["Java", "JavaScript", "AWS", "REST APIs", "SQL", "Testing"], "Enterprise SaaS and CRM platform."),
    ("ServiceNow", ["JavaScript", "Java", "SQL", "REST APIs", "AWS", "Testing"], "Enterprise workflow automation and cloud platform."),
    ("Oracle", ["Java", "SQL", "Python", "System Design", "Linux", "Testing"], "Database, enterprise apps, and infrastructure software."),
    ("SAP", ["Java", "SQL", "Python", "REST APIs", "Cloud", "Testing"], "ERP and enterprise business software."),
    ("Intuit", ["Python", "JavaScript", "SQL", "Machine Learning", "REST APIs"], "Consumer finance software and automation platforms."),
    ("NVIDIA", ["C++", "Python", "CUDA", "Machine Learning", "Linux", "Data Structures"], "AI, GPU, and accelerated computing stack."),
    ("Qualcomm", ["C++", "Python", "Embedded", "Linux", "Testing", "Data Structures"], "Semiconductor and wireless platform engineering."),
    ("IBM", ["Python", "Java", "SQL", "Cloud", "System Design", "Testing"], "Enterprise AI, infrastructure, and consulting solutions."),
    ("PayPal", ["Java", "Python", "SQL", "System Design", "REST APIs", "AWS"], "Digital payments and fintech platform."),
    ("Visa", ["Java", "Python", "SQL", "REST APIs", "System Design", "Cloud"], "Global digital payments infrastructure."),
    ("Mastercard", ["Java", "Python", "SQL", "System Design", "AWS", "Testing"], "Global payments and digital commerce infrastructure."),
    ("JPMorgan Chase", ["Java", "Python", "SQL", "System Design", "Cloud", "Testing"], "Global banking and financial technology platform."),
    ("Goldman Sachs", ["Python", "Java", "SQL", "System Design", "Machine Learning"], "Investment banking and quantitative engineering."),
    ("Walmart Global Tech", ["Java", "Python", "SQL", "AWS", "System Design", "Microservices"], "Retail and supply chain technology platform."),
    ("Target", ["Java", "Python", "JavaScript", "SQL", "Cloud", "Testing"], "Retail tech and omnichannel product engineering."),
    ("Dell Technologies", ["Python", "Java", "Linux", "Cloud", "Testing", "SQL"], "Enterprise hardware and cloud operations platform."),
    ("HP", ["Java", "Python", "Linux", "Cloud", "Testing", "REST APIs"], "Enterprise productivity and hardware engineering."),
    ("Cisco", ["Python", "Java", "Linux", "Networking", "Security", "Testing"], "Networking, security, and enterprise infrastructure."),
    ("VMware", ["Python", "Go", "Linux", "Cloud", "Docker", "Kubernetes"], "Virtualization and cloud-native infrastructure."),
    ("Datadog", ["Python", "Go", "AWS", "Docker", "Kubernetes", "SQL"], "Monitoring, observability, and cloud platform."),
    ("New Relic", ["Python", "JavaScript", "Go", "Cloud", "Testing", "SQL"], "Observability and software monitoring platform."),
    ("Confluent", ["Java", "Go", "Kafka", "System Design", "Docker", "Kubernetes"], "Streaming data and event-driven infrastructure."),
    ("MongoDB", ["Python", "JavaScript", "NoSQL", "System Design", "REST APIs"], "Document database and developer data platform."),
    ("Snowflake", ["Python", "SQL", "Java", "Cloud", "Data Analysis", "Machine Learning"], "Cloud data warehouse and analytics platform."),
    ("Databricks", ["Python", "SQL", "Spark", "Machine Learning", "Cloud", "Data Analysis"], "Lakehouse and data engineering platform."),
    ("Palantir", ["Python", "Java", "SQL", "Machine Learning", "System Design"], "Data analytics and enterprise software for complex operations."),
    ("Thoughtworks", ["Java", "JavaScript", "Python", "Cloud", "Testing", "Agile"], "Consulting and product engineering across multiple domains."),
    ("Accenture", ["Java", "Python", "SQL", "Cloud", "Agile", "Testing"], "Global consulting and enterprise transformation services."),
    ("Deloitte", ["Python", "Java", "SQL", "Cloud", "Agile", "Testing"], "Consulting, data, and enterprise digital transformation."),
    ("Cognizant", ["Java", "Python", "SQL", "Cloud", "REST APIs", "Testing"], "Technology and consulting services for global enterprises."),
    ("Capgemini", ["Java", "Python", "SQL", "Cloud", "Testing", "Agile"], "IT services and digital engineering firm."),
    ("Infosys", ["Java", "Python", "SQL", "Azure", "REST APIs", "Agile"], "Global digital services and enterprise platform consulting."),
    ("TCS", ["Java", "Python", "SQL", "Spring Boot", "REST APIs", "Testing"], "Large-scale enterprise technology and IT services."),
    ("Wipro", ["Java", "Python", "SQL", "Cloud", "Testing", "Agile"], "Enterprise IT services and digital transformation."),
    ("HCLTech", ["Java", "Python", "SQL", "Cloud", "Testing", "Agile"], "Product engineering and digital services company."),
    ("Tech Mahindra", ["Java", "Python", "SQL", "Cloud", "Testing", "AWS"], "Digital transformation and telecom technology services."),
    ("Persistent Systems", ["Java", "Python", "Cloud", "Microservices", "SQL", "Testing"], "Product engineering and digital transformation services."),
    ("Coforge", ["Java", "Python", "SQL", "Cloud", "REST APIs", "Testing"], "Digital engineering and enterprise IT services."),
    ("LTIMindtree", ["Java", "Python", "SQL", "Cloud", "Testing", "Agile"], "Digital engineering and platform modernization."),
    ("Razorpay", ["Java", "Spring Boot", "SQL", "RabbitMQ", "AWS", "Microservices"], "Fintech platform built for scale and payment infrastructure."),
    ("Zoho", ["Java", "JavaScript", "SQL", "REST APIs", "Linux", "System Design"], "Product company with a strong full-stack engineering culture."),
    ("Freshworks", ["JavaScript", "React", "Node.js", "REST APIs", "AWS", "Testing"], "Customer engagement SaaS platform and product engineering."),
    ("Zerodha", ["Python", "Go", "React", "Linux", "System Design", "Data Structures"], "Brokerage platform with a lean and high-scale stack."),
    ("Swiggy", ["Java", "Go", "React", "Microservices", "AWS", "System Design"], "Food delivery scale platform across operations and logistics."),
    ("PhonePe", ["Java", "Spring Boot", "SQL", "Kubernetes", "System Design", "Microservices"], "UPI and fintech infrastructure at scale."),
    ("CRED", ["Go", "Java", "React", "AWS", "Microservices", "System Design"], "Credit and fintech platform with modern engineering."),
    ("Flipkart", ["Java", "Spring Boot", "SQL", "Data Analysis", "AWS", "System Design"], "E-commerce marketplace with complex scale and analytics."),
    ("Paytm", ["Java", "Spring Boot", "SQL", "AWS", "Microservices", "System Design"], "Fintech and commerce ecosystem with large engineering teams."),
    ("Meesho", ["Python", "React", "Node.js", "AWS", "Machine Learning", "SQL"], "Social commerce platform using data and product engineering."),
    ("Groww", ["Java", "Spring Boot", "React", "AWS", "System Design", "SQL"], "Investment platform built around scale and UX."),
    ("Myntra", ["Java", "JavaScript", "React", "Machine Learning", "AWS", "SQL"], "Fashion commerce and recommendation-driven product experience."),
    ("Zomato", ["Java", "Go", "AWS", "Microservices", "System Design", "SQL"], "Food delivery and local commerce platform at scale."),
    ("Navi", ["Java", "Python", "AWS", "Machine Learning", "System Design", "SQL"], "Data-driven fintech product company."),
    ("Dream11", ["Java", "Node.js", "AWS", "System Design", "NoSQL", "Testing"], "Real-time sports platform with internet-scale traffic."),
    ("Postman", ["JavaScript", "Node.js", "React", "AWS", "Microservices", "Testing"], "API platform with developer-first tooling."),
    ("BrowserStack", ["JavaScript", "Testing", "Java", "Docker", "AWS", "Node.js"], "Software testing platform for global developers."),
    ("Ola", ["Go", "Java", "AWS", "Kubernetes", "System Design", "React"], "Mobility platform with cloud and ride-operations engineering."),
    ("Urban Company", ["Java", "Node.js", "React", "AWS", "System Design", "SQL"], "Home services and local commerce marketplace."),
    ("MakeMyTrip", ["Java", "JavaScript", "React", "AWS", "SQL", "System Design"], "Travel booking platform with high-scale consumer products."),
    ("Delhivery", ["Java", "Python", "SQL", "AWS", "System Design", "Data Analysis"], "Logistics and supply chain platform at scale."),
    ("Jio", ["Java", "Python", "AWS", "Kubernetes", "System Design", "Network"], "Telecom and digital ecosystem infrastructure."),
    ("Airtel", ["Java", "Python", "AWS", "System Design", "Networking", "SQL"], "Telecom and digital platform services."),
    ("Upstox", ["Python", "Java", "React", "SQL", "System Design", "Testing"], "Brokerage and fintech product engineering."),
    ("ShareChat", ["Java", "Python", "React", "Machine Learning", "AWS", "SQL"], "Regional social content and recommendation platform."),
    ("Unacademy", ["Python", "JavaScript", "React", "Node.js", "AWS", "Machine Learning"], "Edtech platform and learner-first digital products."),
    ("Byju's", ["Python", "JavaScript", "Node.js", "AWS", "Machine Learning", "React"], "Edtech platform with product engineering and data systems."),
    ("Naukri", ["Java", "Python", "SQL", "Node.js", "AWS", "Testing"], "Recruitment platform and consumer product infrastructure."),
    ("Indeed", ["Java", "Python", "SQL", "Cloud", "System Design", "Testing"], "Global employment marketplace and search platform."),
    ("LinkedIn", ["Java", "Python", "JavaScript", "SQL", "System Design", "Machine Learning"], "Professional network with large-scale data and product systems."),
    ("Reddit", ["Python", "Go", "JavaScript", "SQL", "System Design", "Testing"], "Community platform with content, feed, and scale challenges."),
    ("Shopify", ["Ruby", "JavaScript", "React", "Node.js", "AWS", "SQL"], "Commerce platform and merchant ecosystem."),
    ("Notion", ["TypeScript", "React", "Node.js", "SQL", "AWS", "Testing"], "Productivity and collaboration software."),
    ("Dropbox", ["Python", "Go", "JavaScript", "SQL", "System Design", "AWS"], "Storage, sync, and productivity platform."),
    ("Slack", ["JavaScript", "Node.js", "React", "Java", "Testing", "System Design"], "Real-time collaboration platform."),
    ("Discord", ["Go", "TypeScript", "React", "Node.js", "Engineering", "Testing"], "Real-time communication and gaming platform."),
    ("Figma", ["TypeScript", "React", "Node.js", "JavaScript", "Testing", "System Design"], "Collaborative design and product prototyping platform."),
    ("Canva", ["JavaScript", "TypeScript", "Node.js", "React", "AWS", "Testing"], "Design and publishing platform."),
    ("Pinterest", ["Python", "JavaScript", "Machine Learning", "SQL", "System Design"], "Visual discovery and recommendation platform."),
    ("Twitter", ["Scala", "Java", "Python", "System Design", "Machine Learning", "SQL"], "Social media platform with high-scale content flows."),
    ("Snapchat", ["Java", "Swift", "Kotlin", "Python", "Machine Learning", "AWS"], "Social media and AR product platform."),
    ("ByteDance", ["Java", "Python", "C++", "Machine Learning", "System Design", "SQL"], "Global short-form media and AI ecosystem."),
    ("Nubank", ["Java", "Python", "React", "SQL", "AWS", "System Design"], "Digital banking and fintech platform."),
    ("Plaid", ["Python", "JavaScript", "SQL", "REST APIs", "Testing", "Cloud"], "Financial data and infrastructure platform."),
    ("Robinhood", ["Python", "Java", "JavaScript", "SQL", "Machine Learning", "System Design"], "Trading and finance consumer platform."),
    ("Coinbase", ["JavaScript", "Python", "Go", "SQL", "System Design", "AWS"], "Crypto trading and digital wallet platform."),
    ("Square", ["Java", "JavaScript", "Python", "SQL", "System Design", "Cloud"], "Payments and business tools platform."),
    ("ShopUp", ["Python", "JavaScript", "Node.js", "AWS", "SQL", "REST APIs"], "Commerce and SMB platform in emerging markets."),
    ("Gojek", ["Java", "Go", "Python", "AWS", "System Design", "SQL"], "Super app with mobility, payments, and services."),
    ("Grab", ["Java", "Python", "Go", "AWS", "System Design", "SQL"], "Super app and mobility marketplace."),
    ("Practo", ["Python", "JavaScript", "Node.js", "SQL", "AWS", "Testing"], "Healthcare platform and digital workflow products."),
    ("HealthifyMe", ["Python", "JavaScript", "Node.js", "Machine Learning", "SQL"], "Health-tech platform with data and recommendation products."),
    ("Myntra", ["Java", "JavaScript", "React", "Machine Learning", "AWS", "SQL"], "Fashion commerce experience with recommendations and scale."),
    ("Cult.fit", ["Python", "JavaScript", "Node.js", "AWS", "Machine Learning", "SQL"], "Fitness and wellness platform with consumer product scale."),
    ("Spinny", ["Java", "Python", "React", "Node.js", "AWS", "SQL"], "Auto marketplace and commerce platform."),
    ("CarDekho", ["Java", "Python", "JavaScript", "AWS", "SQL", "Machine Learning"], "Auto marketplace and recommendation platform."),
    ("OYO", ["Java", "Python", "Node.js", "React", "AWS", "System Design"], "Hospitality and marketplace platform."),
    ("NoBroker", ["Java", "Python", "Node.js", "AWS", "SQL", "System Design"], "Real estate marketplace and platform engineering."),
    ("HackerRank", ["Python", "JavaScript", "Node.js", "SQL", "Testing", "Machine Learning"], "Developer assessment and hiring platform."),
    ("CodeChef", ["Python", "JavaScript", "Node.js", "SQL", "Testing", "Machine Learning"], "Coding platform and developer community."),
    ("GeeksforGeeks", ["JavaScript", "Python", "Node.js", "SQL", "Machine Learning"], "Learning platform and technical content ecosystem."),
    ("NVIDIA", ["C++", "Python", "Machine Learning", "Linux", "Data Structures", "CUDA"], "Accelerated computing and AI platform."),
    ("OpenAI", ["Python", "C++", "Machine Learning", "System Design", "Data Structures"], "Foundation model and AI platform research."),
    ("Anthropic", ["Python", "C++", "Machine Learning", "Data Structures", "System Design"], "AI research and model platform company."),
    ("Perplexity", ["Python", "JavaScript", "Machine Learning", "SQL", "System Design"], "AI-powered search and assistant platform."),
    ("Kaggle", ["Python", "SQL", "Machine Learning", "Data Analysis", "Statistics"], "Data science community and ML platform."),
    ("Coursera", ["Python", "JavaScript", "Node.js", "SQL", "Machine Learning"], "Online learning platform and digital education experience."),
    ("Udemy", ["Python", "JavaScript", "Node.js", "AWS", "SQL", "Testing"], "Marketplace for online learning and digital products."),
    ("Akamai", ["Python", "Java", "Linux", "Networking", "System Design", "Cloud"], "CDN and edge platform engineering."),
    ("Cloudflare", ["Go", "Rust", "Python", "Networking", "Linux", "System Design"], "Distributed edge network and security platform."),
    ("Fastly", ["Go", "JavaScript", "Python", "Networking", "Docker", "Cloud"], "Edge delivery and application platform."),
    ("HashiCorp", ["Go", "Python", "Linux", "Docker", "System Design", "Testing"], "Infrastructure automation and cloud platform tools."),
    ("Docker", ["Go", "Python", "Linux", "Docker", "Kubernetes", "Testing"], "Container platform and developer tooling."),
    ("Red Hat", ["Python", "Java", "Linux", "Kubernetes", "Docker", "System Design"], "Enterprise open-source infrastructure platform."),
    ("MongoDB", ["Python", "JavaScript", "NoSQL", "REST APIs", "System Design", "Cloud"], "Document database and app data platform."),
    ("Elastic", ["Java", "Go", "Python", "Search", "System Design", "Cloud"], "Search, observability, and data platform."),
    ("SUSE", ["Python", "Go", "Linux", "Kubernetes", "Docker", "Cloud"], "Enterprise Linux and cloud infrastructure."),
    ("VMware", ["Python", "Go", "Linux", "Cloud", "Docker", "Kubernetes"], "Virtualization and cloud-native enterprise platform."),
    ("Nutanix", ["Python", "Java", "Go", "Linux", "Kubernetes", "Cloud"], "Hyperconverged infrastructure and hybrid cloud."),
    ("Criteo", ["Python", "Java", "SQL", "Machine Learning", "Data Analysis", "System Design"], "Ad-tech and recommendation platform."),
    ("PubMatic", ["Java", "Python", "SQL", "System Design", "Machine Learning"], "Programmatic advertising and ad-tech platform."),
    ("Affle", ["Python", "JavaScript", "Machine Learning", "SQL", "AWS"], "Mobile advertising and consumer tech platform."),
    ("InMobi", ["Java", "Python", "Machine Learning", "AWS", "SQL", "System Design"], "Mobile advertising and app discovery platform."),
    ("OnePlus", ["Java", "Kotlin", "Android", "REST APIs", "Testing", "JavaScript"], "Consumer electronics and mobile platform company."),
    ("Samsung", ["Java", "Kotlin", "Android", "C++", "Linux", "Testing"], "Consumer hardware and mobile platform company."),
    ("Motorola", ["Java", "Kotlin", "Android", "Testing", "REST APIs"], "Mobile hardware and software engineering."),
    ("BharatPe", ["Java", "Python", "SQL", "AWS", "System Design", "REST APIs"], "Fintech platform focused on digital payments and commerce."),
    ("PolicyBazaar", ["Java", "Python", "Node.js", "AWS", "SQL", "Testing"], "Insurtech and digital consumer platform."),
    ("Nykaa", ["Java", "Python", "React", "Node.js", "AWS", "SQL"], "Beauty e-commerce and digital commerce platform."),
    ("PharmEasy", ["Java", "Python", "Node.js", "AWS", "SQL", "REST APIs"], "Healthcare and digital pharmacy platform."),
    ("Gupshup", ["Java", "Python", "Node.js", "REST APIs", "AWS", "SQL"], "Messaging and conversational platform."),
    ("JioMart", ["Java", "Python", "Node.js", "AWS", "SQL", "System Design"], "Retail and ecommerce platform for digital commerce."),
    ("Bharat Matrimony", ["Java", "Python", "SQL", "Node.js", "AWS", "Testing"], "Consumer matchmaking and digital services platform."),
    ("Hexaware", ["Java", "Python", "SQL", "Cloud", "Testing", "Agile"], "Digital transformation and enterprise engineering services."),
    ("Mphasis", ["Java", "Python", "SQL", "Cloud", "Testing", "Agile"], "Application and digital engineering services."),
    ("Sutherland", ["Java", "Python", "SQL", "Cloud", "Testing", "Agile"], "Digital business and customer experience service company."),
    ("EXL", ["Python", "SQL", "Machine Learning", "Data Analysis", "Cloud"], "Analytics and digital operations company."),
    ("Fractal", ["Python", "SQL", "Machine Learning", "Data Analysis", "Cloud"], "AI and analytics transformation services."),
    ("MuSigma", ["Python", "SQL", "Machine Learning", "Data Analysis", "Statistics"], "Analytics and decision intelligence company."),
    ("Tiger Analytics", ["Python", "SQL", "Machine Learning", "Data Analysis", "Statistics"], "Data science and AI consulting company."),
    ("Mindtree", ["Java", "Python", "SQL", "Cloud", "Testing", "Agile"], "Digital engineering and enterprise technology services."),
    ("L&T Technology Services", ["Java", "Python", "SQL", "Cloud", "Testing", "System Design"], "Engineering research and product development services."),
    ("Cybage", ["Java", "Python", "JavaScript", "Cloud", "Testing", "Agile"], "Product engineering services company."),
    ("Zeta", ["Java", "Python", "Node.js", "AWS", "System Design", "SQL"], "Fintech and banking platform technology company."),
    ("FIS", ["Java", "Python", "SQL", "Cloud", "System Design", "Testing"], "Financial technology and payment infrastructure provider."),
    ("Fiserv", ["Java", "Python", "SQL", "REST APIs", "AWS", "Testing"], "Payments and financial software platform."),
    ("Netskope", ["Python", "Go", "Linux", "Security", "Cloud", "Testing"], "Cloud security and network platform."),
    ("Palo Alto Networks", ["Python", "Go", "Linux", "Security", "Networking", "Cloud"], "Cybersecurity platform and threat detection company."),
    ("CrowdStrike", ["Python", "C++", "Linux", "Security", "Cloud", "Testing"], "Cybersecurity and cloud-native endpoint protection."),
    ("Zscaler", ["Python", "Java", "Security", "Cloud", "Linux", "Testing"], "Secure cloud access and zero-trust networking company."),
    ("Verizon", ["Java", "Python", "Cloud", "Networking", "Linux", "SQL"], "Telecom and digital infrastructure company."),
    ("AT&T", ["Java", "Python", "Cloud", "Networking", "Linux", "SQL"], "Telecom and digital connectivity company."),
    ("Comcast", ["Java", "Python", "Cloud", "Networking", "Linux", "Testing"], "Telecom and digital media platform architecture."),
    ("Amdocs", ["Java", "Python", "SQL", "REST APIs", "Cloud", "Testing"], "Telecom and software services company."),
    ("Nokia", ["C++", "Python", "Networking", "Linux", "Cloud", "System Design"], "Telecom and network infrastructure company."),
    ("Ericsson", ["C++", "Python", "Networking", "Linux", "Cloud", "System Design"], "Telecom network, software, and infrastructure company."),
    ("Broadcom", ["C++", "Python", "Linux", "Networking", "System Design", "Testing"], "Semiconductor and infrastructure technology company."),
    ("Intel", ["C++", "Python", "Linux", "System Design", "Cloud", "Testing"], "Semiconductors and platform engineering company."),
    ("AMD", ["C++", "Python", "Linux", "System Design", "Data Structures", "Cloud"], "Semiconductor and high-performance computing company."),
    ("NVIDIA", ["C++", "Python", "Machine Learning", "CUDA", "Linux", "Data Structures"], "AI and accelerated-computing technology platform."),
    ("OpenAI", ["Python", "C++", "Machine Learning", "Data Structures", "System Design"], "AI research and application platform company."),
    ("Anthropic", ["Python", "C++", "Machine Learning", "Data Structures", "System Design"], "AI model development and platform research."),
    ("Perplexity", ["Python", "JavaScript", "Machine Learning", "SQL", "System Design"], "AI-powered search and assistant platform."),
    ("KPMG", ["Python", "SQL", "Machine Learning", "Cloud", "Testing"], "Consulting and analytics transformation firm."),
    ("EY", ["Python", "SQL", "Cloud", "Machine Learning", "Testing"], "Consulting and enterprise digital transformation services."),
    ("PwC", ["Python", "SQL", "Cloud", "Machine Learning", "Testing"], "Professional services and digital transformation consulting."),
    ("Mercari", ["Java", "Python", "Go", "SQL", "System Design", "AWS"], "Marketplace and consumer commerce platform."),
    ("Rakuten", ["Java", "Python", "SQL", "System Design", "Cloud", "Testing"], "E-commerce and digital platform company."),
    ("Bajaj Finserv", ["Java", "Python", "SQL", "System Design", "Cloud", "Testing"], "Financial services and digital platform company."),
    ("Axis Bank", ["Java", "Python", "SQL", "REST APIs", "Cloud", "Testing"], "Banking and financial technology platform."),
    ("HDFC Bank", ["Java", "Python", "SQL", "REST APIs", "Cloud", "Testing"], "Banking technology and digital services platform."),
    ("ICICI Bank", ["Java", "Python", "SQL", "REST APIs", "Cloud", "Testing"], "Banking and digital financial services platform."),
]

_SEED_TITLES = [
    "Software Engineer", "Senior Software Engineer", "Backend Developer",
    "Frontend Developer", "Full Stack Developer", "Data Analyst",
    "Machine Learning Engineer", "DevOps Engineer", "SDE I", "SDE II",
    "QA Automation Engineer", "Product Engineer",
]

_SEED_LOCATIONS = ["Bengaluru", "Bengaluru", "Hyderabad", "Pune", "Chennai", "NCR", "Remote (India)", "Mumbai"]


def _seed_jobs(query: Optional[str], limit: int) -> list[dict]:
    rng = random.Random(42)  # deterministic-ish demo data
    jobs = []
    for i, (company, skills, blurb) in enumerate(_SEED_COMPANIES):
        if query:
            q = query.lower()
            hay = f"{company} {' '.join(skills)} {blurb}".lower()
            if q not in hay and not any(q in s.lower() for s in skills):
                continue
        jobs.append({
            "id": f"seed-{i}",
            "title": rng.choice(_SEED_TITLES),
            "company": company,
            "location": rng.choice(_SEED_LOCATIONS),
            "url": None,
            "type": "full_time",
            "published": f"2026-09-{rng.randint(10, 23):02d}",
            "salary": f"₹{rng.randint(6, 45)} – ₹{rng.randint(46, 90)} LPA",
            "tags": skills[:4],
            "description": f"{company}: {blurb} Core stack: {', '.join(skills)}.",
            "required_skills": skills,
            "source": "seed",
        })
    return jobs[:limit]


def get_companies() -> list[dict]:
    """Company profiles with required skills — used by the matching engine."""
    return [
        {"name": name, "required_skills": skills, "about": blurb}
        for name, skills, blurb in _SEED_COMPANIES
    ]


# ---------------------------------------------------------------- public API

def get_jobs(query: Optional[str] = None, limit: int = 100, live_first: bool = True) -> dict:
    """Return {'jobs': [...], 'source': 'live-remotive'|'live-adzuna'|'cache'|'seed', 'fetched_at': ts}.

    Tries live sources; on any failure falls back to cache then seed data.
    Never raises — the product must always show something.
    """
    errors = []
    if live_first:
        try:
            jobs = _fetch_remotive(query, limit)
            if jobs:
                if len(jobs) < limit:
                    seed_jobs = _seed_jobs(query, max(limit - len(jobs), 0))
                    seen = {job["id"] for job in jobs}
                    for job in seed_jobs:
                        if job["id"] not in seen:
                            jobs.append(job)
                            seen.add(job["id"])
                            if len(jobs) >= limit:
                                break
                with _lock:
                    _cache["ts"] = time.time()
                    _cache["jobs"] = jobs
                return {"jobs": jobs, "source": "live-remotive", "fetched_at": _cache["ts"]}
        except Exception as e:  # noqa: BLE001
            errors.append(f"remotive: {type(e).__name__}")

        try:
            jobs = _fetch_adzuna(query, limit)
            if jobs:
                if len(jobs) < limit:
                    seed_jobs = _seed_jobs(query, max(limit - len(jobs), 0))
                    seen = {job["id"] for job in jobs}
                    for job in seed_jobs:
                        if job["id"] not in seen:
                            jobs.append(job)
                            seen.add(job["id"])
                            if len(jobs) >= limit:
                                break
                with _lock:
                    _cache["ts"] = time.time()
                    _cache["jobs"] = jobs
                return {"jobs": jobs, "source": "live-adzuna", "fetched_at": _cache["ts"]}
        except Exception as e:  # noqa: BLE001
            errors.append(f"adzuna: {type(e).__name__}")

        # fresh cache?
        with _lock:
            if _cache["jobs"] and time.time() - _cache["ts"] < CACHE_TTL_SECONDS:
                jobs = _filter_seed(_cache["jobs"], query, limit)
                return {"jobs": jobs, "source": "cache", "fetched_at": _cache["ts"], "notes": errors}

    seed_jobs = _seed_jobs(query, limit)
    return {
        "jobs": seed_jobs,
        "source": "seed",
        "fetched_at": time.time(),
        "notes": errors or ["live sources unreachable"],
    }


def _filter_seed(jobs: list[dict], query: Optional[str], limit: int) -> list[dict]:
    if not query:
        return jobs[:limit]
    q = query.lower()
    out = [j for j in jobs if q in j["title"].lower() or q in j["company"].lower()
           or any(q in s.lower() for s in j.get("required_skills", []))]
    return out[:limit] or jobs[:limit]
