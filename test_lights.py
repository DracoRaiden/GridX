from firebase_manager import db
import time

print("💡 TESTING HARDWARE...")

print("👉 Sending Action 1 (Pin 14)...")
db.reference('/controls').update({"action": 1})
time.sleep(2)

print("👉 Sending Action 2 (Pin 25)...")
db.reference('/controls').update({"action": 2})
time.sleep(2)

print("👉 Sending Action 3 (Pin 26)...")
db.reference('/controls').update({"action": 3})
time.sleep(2)

print("👉 Turning OFF...")
db.reference('/controls').update({"action": 0})
print("✅ Test Complete.")