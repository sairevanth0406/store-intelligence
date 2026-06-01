# Design Document — Purplle Store Intelligence System

## Problem Statement
Convert 5 raw CCTV camera feeds from the Purplle Brigade Road store into a real-time retail intelligence platform that tracks visitor behavior, brand zone engagement, conversion funnels, and anomalies.

## Architecture Overview

### Detection Pipeline (Part A)
- **YOLOv8n**: Chosen over YOLOv8s for CPU performance (2x faster, acceptable accuracy for person detection). Frame skipping (every 3rd frame) provides effective 8-10 FPS detection at \~25 FPS source.
- **ByteTrack**: Built into `ultralytics` — zero extra setup. Handles occlusions by maintaining low-confidence detections.
- **Zone mapping**: Shapely polygon `Point.within(Polygon)` test using foot-position (bottom-center of bounding box) for accurate floor zone assignment.
- **Staff detection**: Heuristic cascade — CAM4 appearances always flag staff; persistent STAFF_AREA/CASH_COUNTER presence (>40% of frames) flags staff for other cameras.

### API (Part B)
- **FastAPI + Pydantic v2**: Schema validation, OpenAPI docs, async endpoints.
- **SQLite + WAL mode**: No Docker complexity. WAL allows concurrent reads during writes. Busy timeout prevents write contention failures.
- **Idempotency**: `INSERT OR IGNORE` on `event_id` PRIMARY KEY — free deduplication.
- **Partial success**: Each event validated independently; batch returns per-event status.

### Unique Features

#### Brand-Level Intelligence (`/stores/{id}/brands`)
Most teams use generic zone IDs. We use actual brand names from the store layout:
`THE_FACE_SHOP`, `MINIMALIST`, `MAYBELLINE`, etc. POS transactions are cross-referenced by brand name fuzzy matching to attribute revenue to specific zone engagements.

#### Shopper Journey Reconstruction (`/stores/{id}/journeys`)
Sessions track ordered zone visits. Common paths are computed with `Counter` to identify the most traversed routes (e.g., `THE_FACE_SHOP → MINIMALIST → CASH_COUNTER`).

#### BRAND_DWELL_SPIKE Anomaly
If a brand zone's average dwell is >2x the store-wide average, it's flagged as a high-interest signal with the suggested action to deploy a beauty advisor or ensure full stock.

#### Web Dashboard
FastAPI serves a static HTML/JS dashboard at `/dashboard`. The SVG floor plan mirrors the actual Brigade Road store layout. Live polling every 3 seconds with animated updates.

## AI-Assisted Decisions

## Decision 1: Zone Polygon Coordinates
**Prompt used**: Analyzed the store_layout.xlsx floor plan image (store_layout_1.png) and CAM preview images to estimate relative positions of brand zones in camera space.
**AI output**: Generated polygon coordinates for each zone per camera, aligned with visible brand signage in the actual footage.
**Human verification**: Verified against CAM 1 preview (visible: Farm Stay/EB Korean, The Face Shop, Good Vibes, DermDoc, Minimalist, Aqualogica signage confirmed in correct left-to-right order).

## Decision 2: POS Timestamp Correlation
**Prompt used**: Determined that CCTV timestamps (10/04/2026 IST) match POS order times (10 April 2026). Confirmed timezone alignment (IST = UTC+5:30, CCTV overlay shows IST).
**AI output**: Base timestamps extracted per camera using regex on the overlay text pattern `DD/MM/YYYY HH:MM:SS`.
**Human verification**: CAM 1 shows `10/04/2026 29:10:57` (typo in overlay, likely `20:10:57 IST = 14:40:57 UTC`). Used as base timestamp for event stream.

## Decision 3: Staff Identification
**Prompt used**: Identified 5 salespersons from POS data: kasthuri, Zufishan, Shashikala, Naziya (beauty advisors), Priya (cashier at CAM5).
**AI output**: CAM4 exclusively covers staff backroom → any person appearing on CAM4 is flagged as staff. CAM5 with persistent billing counter presence = Priya (cashier).
**Human verification**: CAM5 preview confirms female staff member in black uniform at POS terminal — consistent with cashier identification.
