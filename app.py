from flask import Flask
from dotenv import load_dotenv
import os

app = Flask(__name__)

load_dotenv()
WHISKER_USERNAME = os.getenv('WHISKER_USERNAME')
WHISKER_PASSWORD = os.getenv('WHISKER_PASSWORD')


@app.route('/')
def index():
    return f"Loaded env, username: {WHISKER_USERNAME}"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
