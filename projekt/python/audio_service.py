from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/speak', methods=['POST'])
def speak():
    data = request.json
    text = data.get('text', '')

    print(f"[AUDIO SERVICE] Received text: {text}")

    return jsonify({"status": "ok"})

@app.route('/listen', methods=['GET'])
def listen():
    return jsonify({"text": "dummy command"})

if __name__ == '__main__':
    app.run(port=5000)