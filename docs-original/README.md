# NetriBeat

Heart rate, training load and HRV analysis for athletes, from ECG chest-strap recordings.

This repo holds the **frontend prototype**, the **frontend design spec** and the **backend API spec**.

## Contents

```
netribeat/
├── README.md
├── prototype/
│   └── netribeat.html     Clickable UI prototype (single file, React 18, no build)
└── docs/
    ├── design-spec.md     Frontend design spec: tokens, layout, screens, components, metric definitions
    └── api-spec.yaml      Backend API spec (OpenAPI 3.0)
```

## View the prototype

Open `prototype/netribeat.html` in a browser. Sign in with any valid email and any password.

The prototype uses generated demo data, keeps everything in memory (a refresh resets it), and runs all analysis in the browser.

## Screens

| Screen | Purpose |
|---|---|
| Login | Email + password sign-in |
| Dashboard | Latest session KPIs, RMSSD and training-load trends, recent sessions |
| New recording | Upload files and tag the session to an athlete email |
| Sessions | Searchable, filterable list of all sessions |
| Session view | Five tabs: Overview, ECG & beats, Heart rate, HRV, Load & respiration |
| Settings | Max HR per athlete (age-based, session peaks or manual), with live zone table |

## Status and next steps

| Area | Status |
|---|---|
| UI prototype | Done |
| Design spec | Done (`docs/design-spec.md`) |
| API spec | Draft (`docs/api-spec.yaml`) |
| Backend | Not started. Analysis moves from the browser to the backend; the frontend only renders results. |
| Production frontend | Not started. Rebuild from the prototype's components against the API. |

## Key decision

All signal processing (R-peak detection, artefact correction, HRV, zones, loads) runs **on the backend**. The frontend calls the API and draws what it receives. Formulas and constants both sides must agree on are in `docs/design-spec.md` → *Metric definitions*.
