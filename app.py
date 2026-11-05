import signal
import sys
from flask import Flask, jsonify, request, redirect, Response
from flask_cors import CORS
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from jose import jwt
import datetime
import logging
import traceback
import pandas as pd
import requests
import numpy as np
from sklearn.metrics.pairwise import pairwise_distances
from flask_socketio import SocketIO
import json
from bson import json_util


from config import app_settings, auth_settings

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})  # Apply to all routes
socketio = SocketIO(app, cors_allowed_origins="*")

# MongoDB connection
# mongo_uri = os.getenv('MONGODB_URI', 'mongodb://mongodb:27017/digital_agriculture')
# app_settings.sandbox_server_url = os.getenv('app_settings.sandbox_server_url', 'http://localhost:5001')
# app_settings.param_server_url = os.getenv('app_settings.param_server_url', 'http://localhost:5002')

client = MongoClient(app_settings.mongodb_uri)
# Use the database named in MONGODB_URI (as the deployed pods do), else digital_agriculture.
db = client.get_default_database(default='digital_agriculture')
messages_collection = db['messages']

@app.route('/api/auth/login', methods=['GET'])
def login():
    try:
        tapis_url = f"{auth_settings.tapis_base_url}/v3/oauth2/authorize?client_id={auth_settings.client_id}&redirect_uri={auth_settings.callback_url}&response_type=code"
        return redirect(tapis_url, code=302)


    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/verify', methods=['GET'])
def verify_token():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401

        token = auth_header.split(' ')[1]
        
        username = get_username(token)

        # Get stored Tapis token
        session = db.sessions.find_one({"username": username})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401

        return jsonify({
            "status": "success",
            "username": username,
            "tapis_token": session['tapis_token']
        })

    except jwt.ExpiredSignatureError:
        return jsonify({"status": "error", "message": "Token expired"}), 401
    except jwt.JWTError:
        return jsonify({"status": "error", "message": "Invalid token"}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "app-server"})

# ICICLE CI rollout check: must stay outside /api and report the image's BUILD_SHA.
@app.route('/health', methods=['GET'])
def build_health():
    response = jsonify({
        "status": "ok",
        "build_sha": os.getenv("BUILD_SHA", "unknown"),
        "version": os.getenv("BUILD_VERSION", "unknown")
    })
    response.headers["Cache-Control"] = "no-store"
    return response

def get_username(token):
    """
    Validate a Tapis JWT, `token`, and resolve it to a username.
    """
    # call the userinfo endpoint
    url = f"{auth_settings.tapis_base_url}/v3/oauth2/userinfo"
    headers = {'X-Tapis-Token': token}
    try:
        rsp = requests.get(url, headers=headers, timeout=30)
        rsp.raise_for_status()
        username = rsp.json()['result']['username']
    except Exception as e:
        raise Exception(f"Error looking up token info; debug: {e}")
    return username

@app.route('/api/oauth2/callback', methods=['GET'])
def callback():
    """
    Process a callback from a Tapis authorization server:
      1) Get the authorization code from the query parameters.
      2) Exchange the code for a token
      3) Add the user and token to the session
      4) Redirect to the /data endpoint. 
    """
    code = request.args.get('code')
    if not code:
        raise Exception(f"Error: No code in request; debug: {request.args}")
    url = f"{auth_settings.tapis_base_url}/v3/oauth2/tokens"
    data = {
        "code": code, 
        "redirect_uri": auth_settings.callback_url,
        "grant_type": "authorization_code",
    }
    try:
        response = requests.post(url, data=data, auth=(auth_settings.client_id, auth_settings.client_key), timeout=30)
        response.raise_for_status()
        json_resp = json.loads(response.text)
        token = json_resp['result']['access_token']['access_token']
        tapis_token_info = {
            'access_token': json_resp['result']['access_token']['access_token'],
            'expires_at': json_resp['result']['access_token']['expires_at'],
            'jti': json_resp['result']['access_token']['jti']
        }
        
        username = get_username(json_resp['result']['access_token']['access_token'])

        # Store user session in MongoDB
        db.sessions.update_one(
            {"username": username},
            {
                "$set": {
                    "username": username,
                    "tapis_token": tapis_token_info,
                    "last_login": datetime.datetime.utcnow()
                }
            },
            upsert=True
        )
    except Exception as e:
        raise Exception(f"Error generating Tapis token; debug: {e}")

    return redirect(auth_settings.app_base_url+"/?tapis_token="+str(token)+"&username="+str(username), code=302)


@app.route('/api/get_similar_farmers', methods=['POST'])
def get_similar_farmers():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401

        token = auth_header.split(' ')[1]
        
        username = get_username(token)

        # Get stored Tapis token
        session = db.sessions.find_one({"username": username})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        user_id = username
        
        data = request.get_json()  # Get the JSON data from the request body
        selected_DS_ID = data.get('selectedDataset')  # Extract selectedDataset

        response = None

        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
                }
            
            response = requests.get(f"{app_settings.sandbox_server_url}/api/load_datasets", headers=headers, params={'datasetId' : selected_DS_ID})
        except requests.exceptions.RequestException as e:
            print(f"Error during request: {e}")
            return jsonify({"status": f"Error during request: {e}"}), 500
        
        protectedData = response.json()
        userNames = list(protectedData.keys())

        initiator = userNames.index(user_id)
        clientX = [protectedData[user]['noisyX'] for user in userNames]
        clientY = [protectedData[user]['noisyY'] for user in userNames]
        cropLabels = list(set(clientY[0]))
        clientProportions = []
        for client in clientY:
            row = [0 for i in range(len(cropLabels))]
            for labelY in client:
                row[cropLabels.index(labelY)] += 1
            clientProportions.append(np.array([element/len(client) for element in row]))
        clientProportions = np.array(clientProportions)
        clientAverages = np.array([np.mean(client, axis=0) for client in clientX])

        columns = list([i for i in range(2)])
        df = pd.DataFrame(clientAverages, columns= columns)
        

        distances = pairwise_distances([df[columns].values[initiator]], df[columns].values, metric='euclidean')
        collaboratorsIdx = [b[0] for b in sorted(enumerate(distances[0]),key=lambda i:i[1])]
        collaborators = []
        for idx in collaboratorsIdx[1:4]:
            collaborators.append({ 'username': userNames[idx]})

        return jsonify({'collaborators': collaborators}), 200

    except Exception as e:
        print(e)
        logging.error(f'Unexpected error: {str(e)}')
        logging.error(traceback.format_exc())
        return jsonify({'message': 'An error occurred while processing the file', 'error': str(e)}), 500

@app.route("/api/getMessages", methods=["POST"])
def get_messages():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401

        token = auth_header.split(' ')[1]
        
        username = get_username(token)

        # Get stored Tapis token
        session = db.sessions.find_one({"username": username})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        user_id = username
        
        # The caller can only read their own conversations.
        sender_id = user_id
        receiver_id = request.get_json().get("receiver_id")
        
        # Fetching messages from the database
        messages = db['messages'].find({
            "$or": [
                {"senderID": sender_id, "receiverID": receiver_id},
                {"senderID": receiver_id, "receiverID": sender_id}
            ]
        })

        # Formatting the response
        messages_list = []
        for message in messages:
            messages_list.append({
                "senderID": message["senderID"],
                "receiverID": message["receiverID"],
                "message": message["message"],
                "timestamp": message["timestamp"]
            })
    except Exception as e:
        logging.error(f'Unexpected error: {str(e)}')
        logging.error(traceback.format_exc())
        return jsonify({'message': 'An error occurred ', 'error': str(e)}), 500


    return jsonify(messages_list)

@app.route("/api/sendMessage", methods=["POST"])
def send_message():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401

        token = auth_header.split(' ')[1]
        
        username = get_username(token)

        # Get stored Tapis token
        session = db.sessions.find_one({"username": username})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        user_id = username
        
        data = request.json
        message = {
            # Messages are always sent as the authenticated user.
            "senderID": user_id,
            "receiverID": data["receiverID"],
            "message": data["message"],
            "timestamp": data["timestamp"]
        }

        db['messages'].insert_one(message)
        return jsonify({"status": "Message sent"}), 201
    except Exception as e:
        logging.error(f'Unexpected error: {str(e)}')
        logging.error(traceback.format_exc())
        return jsonify({'message': 'An error occurred ', 'error': str(e)}), 500


@app.route('/api/conversations', methods=['POST'])
def get_conversations():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401

        token = auth_header.split(' ')[1]
        
        username = get_username(token)

        # Get stored Tapis token
        session = db.sessions.find_one({"username": username})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        user_id = username
        
        # The caller can only list their own conversations.
        sender_id = user_id

        # Find all messages where user is either sender or receiver
        messages = db['messages'].find({
            "$or": [
                {"senderID": sender_id},
                {"receiverID": sender_id}
            ]
        })
        
        # Create a dictionary to store latest message timestamp for each partner
        conversation_partners = {}
        for message in messages:
            partner_id = message['receiverID'] if message['senderID'] == sender_id else message['senderID']
            timestamp = message.get('timestamp')
            
            # Update timestamp only if it's more recent
            if partner_id not in conversation_partners or timestamp > conversation_partners[partner_id]['timestamp']:
                conversation_partners[partner_id] = {
                    'partner_id': partner_id,
                    'timestamp': timestamp,
                    'last_message': message.get('content', '')
                }
        # Convert to list and sort by timestamp
        sorted_partners = sorted(
            conversation_partners.values(),
            key=lambda x: x['timestamp'],
            reverse=True  # Most recent first
        )

        return jsonify(sorted_partners), 200
    
    except Exception as e:
        logging.error(f"Error in get_conversations: {str(e)}")
        logging.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/train', methods=['POST'])
def train():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401

        token = auth_header.split(' ')[1]
        
        username = get_username(token)

        # Get stored Tapis token
        session = db.sessions.find_one({"username": username})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        user_id = username
        

        data_received = request.get_json()  # Get the JSON data from the request body
        collaborators = [i['username'] for i in data_received.get('collaborators')]
        # collaborators.append(user_id)
        hyperparameters = data_received.get('hyperparameters')
        
        headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                    }
        response = requests.get(f"{app_settings.sandbox_server_url}/api/get_datasets_metadata", headers=headers, params={'datasetId' : hyperparameters['datasetName']})
        
        metadata = response.json()['metadata']
        num_classes = response.json()['num_classes']
        classes = response.json()['classes']
        
        data = {
                'modelName': hyperparameters['modelName'], 
                'modelType': hyperparameters['modelType'], 
                'modelVisibility': hyperparameters['modelVisibility'],
                'metadata' : metadata,
                'modelOwner' : user_id,
                'modelWeights' : None,
                'modelReadme' : hyperparameters['readme'],
                'collaborators' : collaborators,
                'num_classes' : num_classes,
                'classes' : classes,
                'status' : 'Training'
            }
        result = None
        if hyperparameters['modelVisibility'] == 'Public':
            result = db['models'].insert_one(data)
        else:
            result = db['models'][user_id].insert_one(data)

        model_id = str(result.inserted_id)

        response = requests.post(f"{app_settings.param_server_url}/api/start_training", headers=headers, json={'collaborators': collaborators, 'metadata': metadata, 'model_id' : model_id, "hyperparameters": hyperparameters})
        
        if response:
            print(response)
        return jsonify({'message': 'Training process started.'}), 200 # Return timing
    
    except Exception as e:
        logging.error(f'Unexpected error: {str(e)}')
        logging.error(traceback.format_exc())
        return jsonify({'message': 'An error occurred while processing the file', 'error': str(e)}), 500


@app.route('/api/predict_model', methods=['POST'])
def get_model_prediction():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401

        token = auth_header.split(' ')[1]
        
        username = get_username(token)

        # Get stored Tapis token
        session = db.sessions.find_one({"username": username})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        user_id = username
        

        model_info = request.get_json()['model_info']
        eval_data = request.get_json()['eval_data']
        
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.post(f"{app_settings.sandbox_server_url}/api/predict_eval", 
                                headers=headers, 
                                json={'model_info': model_info, 'eval_data': eval_data})
        
        
        return jsonify(response.json()), 200 

    except Exception as e:
        logging.error(f'Unexpected error: {str(e)}')
        logging.error(traceback.format_exc())
        return jsonify({'message': 'An error occurred while processing the file', 'error': str(e)}), 500

@app.route('/api/get_public_models', methods=['GET'])
def get_public_models():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401

        token = auth_header.split(' ')[1]
        
        username = get_username(token)

        # Get stored Tapis token
        session = db.sessions.find_one({"username": username})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        user_id = username
        
        # Query the datasets collection for the user's datasets
        models = db['models'].find()
        # Remove modelWeights field from each model
        models_list = list(models)
        for model in models_list:
            if 'modelWeights' in model:
                del model['modelWeights']
        
        return jsonify(json_util.dumps(models_list)), 200
    
    except Exception as e:
        logging.error(f'Unexpected error: {str(e)}')
        logging.error(traceback.format_exc())
        return jsonify({'message': 'An error occurred while loading datasets', 'error': str(e)}), 500

@app.route('/api/get_user_models', methods=['GET'])
def get_user_models():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401

        token = auth_header.split(' ')[1]
        
        username = get_username(token)

        # Get stored Tapis token
        session = db.sessions.find_one({"username": username})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        user_id = username
        
        # Query the datasets collection for the user's datasets
        models = db['models'][user_id].find()
        # Remove modelWeights field from each model
        models_list = list(models)
        for model in models_list:
            if 'modelWeights' in model:
                del model['modelWeights']

        return jsonify(json_util.dumps(models_list)), 200
    
    except Exception as e:
        logging.error(f'Unexpected error: {str(e)}')
        logging.error(traceback.format_exc())
        return jsonify({'message': 'An error occurred while loading datasets', 'error': str(e)}), 500
    

# The frontend only talks to this server (through its /api proxy), so the
# farmer-server routes it uses are forwarded unchanged. The farmer-server
# still authenticates every request with the caller's Tapis token.
FARMER_SERVER_ROUTES = {
    'get_user_datasets': ['GET'],
    'delete_dataset': ['GET'],
    'upload_csv': ['POST'],
    'get_dataset_column_info': ['POST'],
    'check_k_anonymity': ['POST'],
    'export_dataset_columns': ['POST'],
}
FORWARDED_REQUEST_HEADERS = {'authorization', 'content-type', 'accept'}
HOP_BY_HOP_RESPONSE_HEADERS = {'content-encoding', 'content-length', 'transfer-encoding', 'connection'}

def forward_to_farmer_server(route):
    try:
        response = requests.request(
            request.method,
            f"{app_settings.sandbox_server_url}/api/{route}",
            params=request.args,
            data=request.get_data(),
            headers={k: v for k, v in request.headers.items() if k.lower() in FORWARDED_REQUEST_HEADERS},
            timeout=300
        )
    except requests.exceptions.RequestException as e:
        logging.error(f'Farmer server request failed: {str(e)}')
        return jsonify({'message': 'Farmer server unavailable'}), 502

    headers = [(k, v) for k, v in response.headers.items() if k.lower() not in HOP_BY_HOP_RESPONSE_HEADERS]
    return Response(response.content, response.status_code, headers)

for route, methods in FARMER_SERVER_ROUTES.items():
    app.add_url_rule(
        f'/api/{route}',
        endpoint=f'farmer_{route}',
        view_func=lambda route=route: forward_to_farmer_server(route),
        methods=methods
    )

if __name__ == '__main__':
    # Exit cleanly on SIGTERM: as PID 1 in the pod the default action is to ignore it.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    app.run(host=app_settings.host, port=app_settings.port, debug=app_settings.debug)


