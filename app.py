from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from jose import jwt
import datetime
from tapipy.tapis import Tapis
import logging
import traceback
import pandas as pd
import datetime
from bson.objectid import ObjectId
import requests
import numpy as np
from sklearn.metrics.pairwise import pairwise_distances
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import threading
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from bson import json_util


# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})  # Apply to all routes
socketio = SocketIO(app, cors_allowed_origins="*")

# MongoDB connection
mongo_uri = os.getenv('MONGODB_URI', 'mongodb://mongodb:27017/digital_agriculture')
REACT_APP_FARMER_API_URL = os.getenv('REACT_APP_FARMER_API_URL', 'http://digital-agriculture-sandbox-farmer-server-1:5001')
REACT_APP_PARAM_API_URL = os.getenv('REACT_APP_PARAM_API_URL', 'http://digital-agriculture-sandbox-param-server-1:5002')

client = MongoClient(mongo_uri)
db = client.digital_agriculture
messages_collection = db['messages']

# TACC Configuration
JWT_SECRET = '6554a9038d6a07bbf3cb17973c13ce2c5f24a71c247210b1f2a8d04cfb8a6907a102064629058d7d89ed4d03a5503fa485e3898346f3baeef1ed510268e680f65d6d7ccaed5ca755586702e55142e1c07e53f5b38b7055b4bb55a70baf0dcdc0d4150347041a1509fc7d12d705ffe4c8e9ff9cb8f9bba5ffd6129128b62e84de4e9087d21d342a10d87a53c59eec2323dcf3a3d2276d62793df37c5e96eacbabc44f1ce1930e7e8ceb97c88f83d75d4fdcb2cebda1ceea7b99294c6d0c4db8fa71d2295b7b73f80813a734447983d47f430d0dddbd90c5ff81a35b46cad10cde33901456e3fe6f7166152366693224a072d7182b40c38bbf04c3ccf76ff3b6db'  # Change this in production

def create_jwt_token(username):
    """Create a JWT token for the authenticated user"""
    payload = {
        'username': username,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=1)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')



@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({"status": "error", "message": "Username and password are required"}), 400

        # Create Tapis client and authenticate
        t = Tapis(
            base_url="https://tacc.tapis.io",
            username=username,
            password=password
        )

        # Get tokens from Tapis
        t.get_tokens()

        if not t.access_token:
            return jsonify({"status": "error", "message": "Authentication failed"}), 401

        # Create JWT token for our application
        token = create_jwt_token(username)
        
        # Extract token information
        tapis_token_info = {
            'access_token': t.access_token.access_token,
            'expires_at': t.access_token.expires_at.isoformat(),
            'jti': t.access_token.jti,
            'original_ttl': t.access_token.original_ttl
        }

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

        return jsonify({
            "status": "success",
            "token": token,
            "username": username,
            "tapis_token": tapis_token_info
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/verify', methods=['GET'])
def verify_token():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401

        token = auth_header.split(' ')[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        
        # Get stored Tapis token
        session = db.sessions.find_one({"username": payload['username']})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401

        return jsonify({
            "status": "success",
            "username": payload['username'],
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


@app.route('/api/get_similar_farmers', methods=['POST'])
def get_similar_farmers():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401
        
        token = auth_header.split(' ')[1]

        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        
        # Get stored Tapis token
        session = db.sessions.find_one({"username": payload['username']})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        user_id = payload['username']
        data = request.get_json()  # Get the JSON data from the request body
        selected_DS_ID = data.get('selectedDataset')  # Extract selectedDataset
        print("sad",selected_DS_ID)

        response = None

        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
                }
            
            response = requests.get(f"{REACT_APP_FARMER_API_URL}/api/load_datasets", headers=headers, params={'datasetId' : selected_DS_ID})
        except requests.exceptions.RequestException as e:
            print(f"Error during request: {e}")
            return jsonify({"status": f"Error during request: {e}"}), 500
        
        protectedData = response.json()
        userNames = list(protectedData.keys())
        print(userNames)
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

@app.route("/getMessages", methods=["POST"])
def get_messages():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401
        
        token = auth_header.split(' ')[1]

        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        
        # Get stored Tapis token
        session = db.sessions.find_one({"username": payload['username']})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        sender_id = request.get_json().get("sender_id")
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

@app.route("/sendMessage", methods=["POST"])
def send_message():
    data = request.json
    message = {
        "senderID": data["senderID"],
        "receiverID": data["receiverID"],
        "message": data["message"],
        "timestamp": data["timestamp"]
    }

    db['messages'].insert_one(message)
    return jsonify({"status": "Message sent"}), 201

@app.route('/conversations', methods=['POST'])
def get_conversations():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401
        
        token = auth_header.split(' ')[1]

        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        
        # Get stored Tapis token
        session = db.sessions.find_one({"username": payload['username']})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        sender_id = request.get_json().get("sender_id")
        print(sender_id)
        if not sender_id:
            return jsonify({"error": "sender_id is required"}), 400

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

@app.route('/train', methods=['POST'])
def train():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Invalid token"}), 401
        
        token = auth_header.split(' ')[1]

        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        
        # Get stored Tapis token
        session = db.sessions.find_one({"username": payload['username']})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
    
        user_id = payload['username']

        data_received = request.get_json()  # Get the JSON data from the request body
        collaborators = [i['username'] for i in data_received.get('collaborators')]
        hyperparameters = data_received.get('hyperparameters')
        
        headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                    }
        response = requests.get(f"{REACT_APP_FARMER_API_URL}/api/get_datasets_metadata", headers=headers, params={'datasetId' : hyperparameters['datasetName']})
        
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

        response = requests.post(f"{REACT_APP_PARAM_API_URL}/api/start_training", headers=headers, json={'collaborators': collaborators, 'metadata': metadata, 'model_id' : model_id, "hyperparameters": hyperparameters})
        
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

        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        
        # Get stored Tapis token
        session = db.sessions.find_one({"username": payload['username']})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
    
        user_id = payload['username']

        model_info = request.get_json()['model_info']
        eval_data = request.get_json()['eval_data']
        
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.post(f"{REACT_APP_FARMER_API_URL}/api/predict_eval", 
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

        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        
        # Get stored Tapis token
        session = db.sessions.find_one({"username": payload['username']})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        user_id = payload['username']
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

        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        
        # Get stored Tapis token
        session = db.sessions.find_one({"username": payload['username']})
        if not session:
            return jsonify({"status": "error", "message": "Session not found"}), 401

        # Check if Tapis token is expired
        expires_at = datetime.datetime.fromisoformat(session['tapis_token']['expires_at'])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if now_utc > expires_at:
            return jsonify({"status": "error", "message": "Tapis token expired"}), 401
        
        user_id = payload['username']
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
    

@app.route('/api/test', methods=['GET'])
def test():
    # Find all messages where user is either sender or receiver
    collections = db['datasets']['osamazafar98'].find({})
    documents_to_copy = list(collections.sort('_id', 1).skip(1))

    if not documents_to_copy:
        return jsonify({"status": "error", "message": "No documents found to copy (or only one document exists)."})

    # Ensure we have exactly 4 documents if that's the strict requirement,
    # or adjust if you want to copy all available documents after the first.
    # For "last 4 documents", if source has 5, this should work.
    # If source has less than 5, this will copy whatever is available after the first.
    if len(documents_to_copy) < 4:
        print(f"Warning: Found only {len(documents_to_copy)} documents to copy after skipping the first.")
    
    # Define the new collection names
    new_collection_names = ['Test1', 'Test2', 'Test3', 'Test4']
    
    # This will hold status messages for each operation
    results = {}

    # Loop through the new collection names and the documents to copy
    # We use zip to pair them up. If there are fewer than 4 documents to copy,
    # zip will naturally stop at the shortest sequence.
    for i, (new_name, doc) in enumerate(zip(new_collection_names, documents_to_copy)):
        target_collection = db['datasets'][new_name] # Access the new collection (it will be created if it doesn't exist)
        
        # Remove the '_id' field from the document to be inserted.
        # MongoDB automatically generates a new unique _id for each new insertion,
        # preventing 'DuplicateKeyError' if the original _id were kept.
        if '_id' in doc:
            del doc['_id']
        
        try:
            inserted_result = target_collection.insert_one(doc)
            results[new_name] = {
                "status": "success",
                "inserted_id": str(inserted_result.inserted_id),
                "message": f"Document copied to {new_name}"
            }
        except Exception as e:
            results[new_name] = {
                "status": "error",
                "message": f"Failed to insert document into {new_name}: {str(e)}"
            }
    
    return jsonify(json.dumps('Done', default=str)), 200
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=True) 


os.environ["APP_CONFIG_PATH"] = "./config.yaml"

from iciflaskn import icicle_flaskn
from iciflaskn import auth
from iciflaskn.config import config

@app.route('/oauth_login', methods=['GET'])
def oauth2_login():
    """
    Check for the existence of a login session, and if none exists, start the OAuth2 flow.
    """
    authenticated, _, _ = auth.is_logged_in()
    # if already authenticated, redirect to the root URL
    if authenticated:
        result = {'path':'/', 'code': 302}
        return result
    # otherwise, start the OAuth flow
    callback_url = f"{config['app_base_url']}/oauth2/callback"
    tapis_url = f"{config['tapis_base_url']}/v3/oauth2/authorize?client_id={config['client_id']}&redirect_uri={callback_url}&response_type=code"
    # print('no, not auth, redirect to:',tapis_url)
    result = {'path': tapis_url, 'code':302}
    return jsonify(result)