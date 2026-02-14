import json
import os
import firebase_admin
from firebase_admin import credentials, db
import random
import time

# --- SETUP ---
# Load service account key path from environment variable
SERVICE_ACCOUNT_PATH = os.getenv("SERVICE_ACCOUNT_PATH", "serviceAccountKey.json")
if not os.path.exists(SERVICE_ACCOUNT_PATH):
    raise FileNotFoundError(f"Service account key not found at {SERVICE_ACCOUNT_PATH}. Set SERVICE_ACCOUNT_PATH env var or ensure serviceAccountKey.json exists.")

cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)

with open(SERVICE_ACCOUNT_PATH, "r", encoding="utf-8") as key_file:
    project_id = json.load(key_file).get("project_id")
    if not project_id:
        raise RuntimeError(f"serviceAccountKey.json at {SERVICE_ACCOUNT_PATH} missing project_id")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        "databaseURL": f"https://{project_id}-default-rtdb.firebaseio.com/"
    })

# --- CONTROLLERS ---

def reset_simulation():
    """Resets the world to a starting state for the Demo."""
    print("🔄 Resetting World State...")
    ref = db.reference('/')
    
    initial_state = {
        "grid": {
            "status": "ONLINE",      # ONLINE / BLACKOUT
            "price_per_unit": 22.0,  # Controlled by Knob 1 later
            "voltage": 220
        },
        "house_a": {
            "role": "PRODUCER",
            "solar_output": 0.0,     # Controlled by Knob 2 later
            "battery_level": 85,     # Percentage
            "wallet_balance": 5000,  # PKR
            "current_load": 200,     # Watts
            "agent_log": "System Active. Monitoring production."
        },
        "house_b": {
            "role": "CONSUMER",
            "solar_output": 0.0,
            "battery_level": 15,     # LOW BATTERY triggers the need
            "wallet_balance": 2000,  # PKR
            "current_load": 1500,    # Watts (AC running)
            "agent_log": "System Active. Battery Critical."
        },
        "market": {
            "latest_transaction": "None",
            "transaction_price": 0,
            "active_contract": False
        },
        "simulation": {
            "clock": "00:00"
        },
        "community": {
            "total_donated_kwh": 0
        },
        "visuals": {
            "led_mode": "IDLE"       # IDLE, GRID_TO_B, A_TO_B, BLACKOUT
        }
    }
    
    ref.set(initial_state)
    print("✅ World Reset Complete.")

def update_sensor_data(house, key, value):
    """Used to simulate hardware if hardware fails."""
    ref = db.reference(f'/{house}')
    ref.update({key: value})

def get_full_state():
    """Returns the entire JSON snapshot."""
    ref = db.reference('/')
    return ref.get()

if __name__ == "__main__":
    reset_simulation()