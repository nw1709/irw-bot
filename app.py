import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
import PyPDF2
import os  

if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gdrive_creds"]["json"]
    )
    drive_service = build('drive', 'v3', credentials=creds)
else: 
    from google.colab import drive
    drive.mount('/content/drive')

st.title("🔍 IRW-Bot mit Langzeitgedächtnis")
st.write("Läuft erfolgreich! 🎉")
