"""
Live event streamer — feeds events one by one to the API with delays on the 2026-04-10 timeline.
Allows visualising the web dashboard updating in real time without breaking historical windows.
Purplle Store Intelligence System.
"""
import time
import uuid
import random
import requests
from datetime import datetime, timezone, timedelta

API_URL = "http://localhost:8000"
STORE_ID = "STORE_BLR_002"

ZONES = [
    "EB_KOREAN", "THE_FACE_SHOP", "GOOD_VIBES", "DERMDOC", "MINIMALIST",
    "AQUALOGICA", "LAKME_SKIN", "ACCESSORIES", "MAYBELLINE", "FACES_CANADA",
    "LAKME", "COLORBAR_SUGAR", "SWISS_BEAUTY", "RENEE_NYBAE", "ALPS_GOODNESS",
    "STREAX", "FRAGRANCE", "NAIL_UNIT", "MAKEUP_UNIT", "CASH_COUNTER", "PMU"
]


def make_event(event_type, person_id, zone_id=None, camera_id="CAM1", dwell_s=None, is_staff=False, timestamp=None):
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "camera_id": camera_id,
        "event_type": event_type,
        "person_id": person_id,
        "is_staff": is_staff,
        "zone_id": zone_id,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "dwell_seconds": dwell_s,
        "confidence": round(random.uniform(0.8, 1.0), 2),
        "metadata": {"source": "demo"}
    }


def main():
    print("=========================================")
    print(" [START] Starting Real-Time Event Streamer (2026-04-10 Timeline)")
    print(f" Target API: {API_URL}")
    print(" Ingesting new events every 1.5s...")
    print(" Keep your dashboard open to watch it update!")
    print("=========================================")

    # Clear only simulated events from events and sessions so we don't destroy real YOLO results
    try:
        import sqlite3
        db = sqlite3.connect("data/store_intelligence.db")
        # Clear previous demo events
        cursor = db.execute("DELETE FROM events WHERE person_id LIKE 'VIS_%' OR metadata LIKE '%\"source\": \"demo\"%'")
        deleted_events = cursor.rowcount
        cursor = db.execute("DELETE FROM sessions WHERE person_id LIKE 'VIS_%'")
        deleted_sessions = cursor.rowcount
        db.commit()
        db.close()
        print(f"[INFO] Cleared {deleted_events} simulated events and {deleted_sessions} sessions from DB.")
    except Exception as e:
        print(f"[WARNING] Could not clear simulated data: {e}")

    active_customers = {}  # person_id -> state

    # Start simulation time at 2026-04-10 14:45:00 UTC (matches CCTV/POS timeline)
    sim_time = datetime(2026, 4, 10, 14, 45, 0, tzinfo=timezone.utc)

    # Stream 500 events
    for step in range(500):
        events_batch = []

        # Advance simulator time
        sim_time += timedelta(seconds=random.randint(5, 15))
        ts_str = sim_time.isoformat()

        # Decide action: entry, transition, or exit
        action = random.choice(["entry", "transition", "exit", "idle"])

        if action == "entry" or not active_customers:
            # Add a new customer
            person_id = f"VIS_{random.randint(1000, 9999)}"
            cam = f"CAM{random.randint(1, 5)}"
            active_customers[person_id] = {
                "cam": cam,
                "current_zone": None,
                "entry_time": ts_str,
                "visited": []
            }
            events_batch.append(make_event("ENTRY", person_id, camera_id=cam, timestamp=ts_str))
            print(f"[ENTRY] ({ts_str}) Visitor {person_id} entered F.O.H")

        elif action == "transition":
            # Select an active customer to browse a zone
            person_id = random.choice(list(active_customers.keys()))
            cust = active_customers[person_id]
            zone = random.choice(ZONES)

            if cust["current_zone"]:
                # Exit previous zone
                dwell_s = random.uniform(10, 45)
                events_batch.append(make_event("ZONE_EXIT", person_id, cust["current_zone"], camera_id=cust["cam"],
                                               dwell_s=dwell_s, timestamp=ts_str))
                events_batch.append(make_event("DWELL", person_id, cust["current_zone"], camera_id=cust["cam"],
                                               dwell_s=dwell_s, timestamp=ts_str))

            cust["current_zone"] = zone
            cust["visited"].append(zone)
            events_batch.append(make_event("ZONE_ENTER", person_id, zone, camera_id=cust["cam"], timestamp=ts_str))
            print(f"[BROWSE] ({ts_str}) Visitor {person_id} entered zone {zone}")

        elif action == "exit" and active_customers:
            # Select a customer to checkout and exit
            person_id = random.choice(list(active_customers.keys()))
            cust = active_customers[person_id]

            if cust["current_zone"]:
                # Exit previous zone
                dwell_s = random.uniform(5, 20)
                events_batch.append(make_event("ZONE_EXIT", person_id, cust["current_zone"], camera_id=cust["cam"],
                                               dwell_s=dwell_s, timestamp=ts_str))
                events_batch.append(make_event("DWELL", person_id, cust["current_zone"], camera_id=cust["cam"],
                                               dwell_s=dwell_s, timestamp=ts_str))

            # 60% chance of billing counter visit + purchase
            if random.random() < 0.60:
                events_batch.append(make_event("ZONE_ENTER", person_id, "CASH_COUNTER", camera_id="CAM5", timestamp=ts_str))
                # Emit CHECKOUT to simulate payment
                events_batch.append(make_event("CHECKOUT", person_id, "CASH_COUNTER", camera_id="CAM5", timestamp=ts_str))
                print(f"[PURCHASE] ({ts_str}) Visitor {person_id} bought items at billing counter!")

            events_batch.append(make_event("EXIT", person_id, camera_id=cust["cam"], timestamp=ts_str))
            del active_customers[person_id]
            print(f"[EXIT] ({ts_str}) Visitor {person_id} exited store.")

        # Post events
        if events_batch:
            try:
                resp = requests.post(f"{API_URL}/events/ingest", json={"events": events_batch})
                resp.raise_for_status()
            except Exception as e:
                print(f"[ERROR] Failed to ingest: {e}")

        time.sleep(1.5)

    print("Live simulation complete!")


if __name__ == "__main__":
    main()
