
import json
import getpass
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:5000"


def send_request(path, method="GET", data=None, admin_key=None):
    headers = {"Content-Type": "application/json"}

    if admin_key:
        headers["X-Admin-Key"] = admin_key

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers=headers,
        method=method
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    print("\n=== FEDEX Express Backend Tester ===\n")

    # Check whether the backend is running
    try:
        health = send_request("/api/health")
        print("1. Backend connection: OK")
        print(health.get("message", health))
    except Exception as error:
        print("Cannot connect to the backend.")
        print("Make sure python app.py is running.")
        print("Details:", error)
        return

    # Ask for the admin key without displaying it
    admin_key = getpass.getpass(
        "\nEnter your backend admin key (hidden): "
    )

    shipment = {
        "sender_name": "Test Sender",
        "receiver_name": "Test Receiver",
        "origin": "Osaka, Japan",
        "destination": "Tokyo, Japan",
        "description": "Test shipment created by Python",
        "estimated_delivery": "2026-10-25"
    }

    try:
        result = send_request(
            "/api/shipments",
            method="POST",
            data=shipment,
            admin_key=admin_key
        )

        tracking_number = result.get("tracking_number")

        if not tracking_number:
            print("\nShipment response:")
            print(json.dumps(result, indent=2))
            print("No tracking_number was returned.")
            return

        print("\n2. Shipment created successfully!")
        print("Tracking number:", tracking_number)

        # Immediately test tracking
        tracking = send_request(
            "/api/track/" + tracking_number
        )

        print("\n3. Tracking lookup: OK")
        print(json.dumps(tracking, indent=2))

    except urllib.error.HTTPError as error:
        print("\nRequest failed with HTTP status:", error.code)
        print(error.read().decode("utf-8"))
        print(
            "\nCheck your admin key and the backend response."
        )
    except Exception as error:
        print("\nSomething went wrong:", error)


if __name__ == "__main__":
    main()
