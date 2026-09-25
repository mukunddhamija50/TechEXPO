# SkillMatch

AI-powered resume maker & scanner + real-time job feed + company-fit matching + skill-gap roadmaps + skill tests with % scores.

## Features

| # | Feature | What it does |
|---|---------|--------------|
| 1 | **Resume Maker** (`/api/resume/generate`) | Turns a structured profile into a polished, ATS-friendly resume. Rewrites weak phrasing ("responsible for…" → strong action verbs), orders skills to match the target role, mines raw text for extra skills, and returns improvement suggestions. |
| 2 | **Resume Scanner** (`/api/resume/scan`) | Parses pasted resume text: detects skills from a 55+ skill taxonomy (with aliases), estimates seniority, extracts contact/education, and produces an ATS-readiness score (0–100) with specific fixes. |
| 3 | **Real-time job API** (`/api/jobs`) | Live listings from the public **Remotive** API (no key needed). Optional **Adzuna** support (set `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`). 10-minute cache, and a built-in curated company dataset as final fallback so the product never shows an empty screen. |
| 4 | **Company Match** (`/api/match/companies`) | Ranks companies by fit % against your skills (weighted matching), split into *Ready now (70%+)* / *Close* / *Stretch*, with matched vs missing skills per company. |
| 5 | **Skill Gap Roadmap** (`/api/match/gap`) | For any company you're *not* ready for: which skills are missing, in what order to learn them (highest-impact first), weekly schedule, free learning resources, and your projected fit % after completing the roadmap. |
| 6 | **Skill Tests** (`/api/tests/...`) | Per-skill quizzes with MCQ + code-output questions ("what does this print?"). Scored as a % with band (Beginner → Expert), per-question explanations, and 75%+ adds the skill as *verified* to your profile. |

## Run it

```bash
cd skillmatch
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- Web app: http://localhost:8000
- Interactive API docs (Swagger): http://localhost:8000/docs

## Project layout

```
skillmatch/
├── app/
│   ├── main.py         # FastAPI routes + serves the web UI
│   ├── skills.py       # skill taxonomy + extraction engine
│   ├── job_sources.py  # real-time job layer: Remotive/Adzuna → cache → seed
│   ├── resume_maker.py # resume generation engine
│   ├── scanner.py      # resume parsing + ATS scoring
│   ├── matcher.py      # company fit matching + gap roadmap
│   └── test_bank.py    # skill question bank + grading
├── static/index.html   # single-page web app
└── requirements.txt
```

## API quick reference

```bash
# live jobs
curl "http://localhost:8000/api/jobs?query=python&limit=10"

# scan a resume (paste text)
curl -X POST http://localhost:8000/api/resume/scan \
  -H 'Content-Type: application/json' \
  -d '{"text": "Mukund ... Python, Django, SQL, Docker ..."}'

# generate a resume
curl -X POST http://localhost:8000/api/resume/generate \
  -H 'Content-Type: application/json' \
  -d '{"name":"Mukund","target_role":"Backend Developer","skills":["Python","SQL"],"projects":[{"name":"X","description":"Flask app used by 500 students"}]}'

# match companies
curl -X POST http://localhost:8000/api/match/companies \
  -H 'Content-Type: application/json' \
  -d '{"skills": ["Python","SQL","Docker","REST APIs","Git"]}'

# gap analysis for a target company
curl -X POST http://localhost:8000/api/match/gap \
  -H 'Content-Type: application/json' \
  -d '{"skills": ["Python","SQL"], "company": "Razorpay"}'

# take a skill test
curl http://localhost:8000/api/tests/Python
curl -X POST http://localhost:8000/api/tests/Python/submit \
  -H 'Content-Type: application/json' \
  -d '{"answers": [1,2,1,0,1,1,1,1]}'
```

## Design decisions

- **No LLM dependency by default.** The "AI" parts (skill extraction, phrasing rewrite, fit scoring, gap prioritisation, ATS findings) are a self-contained rule/weight engine — zero API cost, works offline, deterministic and testable. Each module is small and single-purpose, so you can later drop an LLM into `resume_maker._polish()` or `scanner` without touching the rest.
- **The jobs layer never fails.** Live API → 10-min cache → curated seed dataset. The UI shows a badge telling the user which source is active.
- **Fit % is weighted, not a raw count.** Core engineering skills (System Design, Microservices, ML, cloud) move the score more than soft skills, so "ready" actually means ready.
- **Tests gate the profile.** A skill only becomes *verified* at 75%+, which keeps the resume-maker honest.

## Notes / limitations

- The seed company dataset is indicative (20 well-known Indian tech companies with typical stacks) — swap in your own database or a different jobs API by editing `app/job_sources.py`.
- `scan/file` accepts text-based uploads (.txt/.md). For PDF parsing add `pdfplumber` and decode before calling `scanner.scan_resume`.
- To enable Adzuna (extra coverage): set env vars `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` before starting the server.
