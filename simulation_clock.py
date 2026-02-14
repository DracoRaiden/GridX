import pandas as pd
import time
from firebase_manager import db

def run_simulation():
    df = pd.read_csv("simulation_data.csv")
    print("⏳ Starting 24-Hour Simulation Loop...")
    
    # We loop through the CSV rows
    for index, row in df.iterrows():
        print(f"⏰ SIM TIME: {row['timestamp']} | Grid: {row['grid_status']}")
        
        # 1. Update World State in Firebase
        updates = {
            "simulation/clock": row['timestamp'],
            "grid/status": row['grid_status'],
            "grid/price": row['grid_price'],
            
            # House A (Producer) Physical Inputs
            "house_a/solar_input": row['house_a_solar'],
            "house_a/current_load": row['house_a_load'],
            
            # House B (Consumer) Physical Inputs
            "house_b/current_load": row['house_b_load']
        }
        
        db.reference('/').update(updates)
        
        # 2. Wait for Agents to React (5 Seconds = 30 simulated minutes)
        time.sleep(8) 

if __name__ == "__main__":
    run_simulation()