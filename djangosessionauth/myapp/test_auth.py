import requests

BASE_URL = "http://127.0.0.1:8000/api"

session = requests.Session()

# Register
response = session.post(
    f"{BASE_URL}/register/",
    json={"username": "ayan", "password": "123456"}
)
print("Register:", response.json())

# Login
response = session.post(
    f"{BASE_URL}/login/",
    json={"username": "ayan", "password": "123456"}
)
print("Login:", response.json())

# Protected
response = session.get(f"{BASE_URL}/protected/")
print("Protected:", response.json())

# Logout
response = session.get(f"{BASE_URL}/logout/")
print("Logout:", response.json())
