import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
import PyPDF2
import os

if "gdrive_creds" in st.secrets:  # Prüft direkt die Streamlit Secrets
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gdrive_creds"]
    )
    drive_service = build('drive', 'v3', credentials=creds)
    st.success("✅ Mit Google Drive verbunden!")
else:
    st.error("Fehler: Google Drive-Anmeldedaten fehlen. Bitte Secrets prüfen.")

# App-UI
st.title("🦊 Bot mit Langzeitgedächtnis")
st.markdown("""
    **Willkommen!** Mein Wissen wird in Google Drive gespeichert.  
    Lade die Aufgabe einfach hoch!
""")
