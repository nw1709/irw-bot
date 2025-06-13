import os
from pyngrok import ngrok
import subprocess

os.system("pkill -f ngrok")


PORT = 8501
NGROK_TOKEN = "2ySRhpIJpvLjTWQLAiqxyHmI5Vy_4fRVTCmnNCKqVMD7jEcnq"


!pip install -q pyngrok streamlit


ngrok.set_auth_token(NGROK_TOKEN)


process = subprocess.Popen([
    "streamlit", "run", "app.py",
    "--server.port", str(PORT),
    "--server.headless", "true",
    "--browser.serverAddress", "0.0.0.0"
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


public_url = ngrok.connect(PORT)
print("🔗 Öffentlicher Link:", public_url)
