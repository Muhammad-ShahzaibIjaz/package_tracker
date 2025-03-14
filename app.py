from flask import Flask, jsonify
import requests
from requests.auth import HTTPBasicAuth
import uuid

# Flask app setup
app = Flask(__name__)

# UPS Credentials
UPS_CLIENT_ID = '0PmRLNeLx8nn4SZBdo1bthGMecGXSc4BYgiYFJAlfW8X6hv6'
UPS_CLIENT_SECRET = '9plm8W6Uxz0hDWDiSPzyvjIXyCxdfZ0AnzkGZqRxiTLNh19xZWlInoHoCk1C5qJ5'
UPS_BASE_URL = 'https://onlinetools.ups.com'


# Get UPS OAuth Token
def get_ups_token():
    try:
        url = f"{UPS_BASE_URL}/security/v1/oauth/token"
        response = requests.post(
            url,
            auth=HTTPBasicAuth(UPS_CLIENT_ID, UPS_CLIENT_SECRET),
            data={'grant_type': 'client_credentials'}
        )
        if response.status_code != 200:
            return f"Failed to get token: {response.json()}"
        
        token = response.json().get('access_token')
        if not token:
            raise Exception(f"Failed to get token: {response.json()}")
        return token
    except Exception as e:
        return f"Error getting UPS token: {e}"


# Track UPS Package
def track_package(tracking_number):
    try:
        token = get_ups_token()
        if 'Error' in token:
            return {"error": token}

        url = f"{UPS_BASE_URL}/api/track/v1/details/{tracking_number}"
        
        # Generate a unique transaction ID using UUID
        trans_id = str(uuid.uuid4())  
        transaction_src = "testing"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "transId": trans_id,
            "transactionSrc": transaction_src
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            return {
                "error": f"Failed to track package: {response.status_code}",
                "details": response.json()
            }

        data = response.json()

        # Check if UPS responded with trackResponse data
        if "trackResponse" not in data:
            raise Exception("Invalid response format from UPS API")

        return data["trackResponse"]

    except requests.exceptions.RequestException as e:
        return {"error": f"Request error: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}


# Flask Route
@app.route('/track/<tracking_number>', methods=['GET'])
def track(tracking_number):
    result = track_package(tracking_number)
    return jsonify(result)


# Start Flask server (bind to all interfaces)
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)