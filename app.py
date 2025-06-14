import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PIL import Image
import google.generativeai as genai
from anthropic import Anthropic
import io
import zipfile
import os

# --- UI-Einstellungen ---
st.title("🦊 Koifox-Bot")
st.markdown("""
    *This application uses Google's Gemini for OCR and Anthropic's Claude for answering advanced accounting questions.*  
    *Made with coffee, deep minimal and tiny gummy bears*  
""")

# --- Google Drive-Verbindung ---
if "gdrive_creds" in st.secrets:
    creds = service_account.Credentials.from_service_account_info(st.secrets["gdrive_creds"])
    drive_service = build("drive", "v3", credentials=creds)
    st.success("✅ Mit Google Drive verbunden!")
   try:
        results = drive_service.files().list(pageSize=1, fields="files(id, name)").execute()
        st.write("Debug: Erste Datei im Drive:", results.get('files', []))
    except Exception as e:
        st.error(f"Debug: Verbindungstest fehlgeschlagen: {str(e)}")
else:
    st.error("Google Drive-Anmeldedaten fehlen.")

# --- Funktion zum Laden von Wissen aus Drive ---
def load_knowledge_from_drive(drive_service, file_id="1ymKuU_wjSUmrO_DMpsb54SwvBTULyexG"):
    try:
        # 1. Prüfe Datei-Metadaten
        file_meta = drive_service.files().get(
            fileId=file_id,
            fields="name,mimeType,size"
        ).execute()
        st.write("📁 Datei gefunden:", file_meta["name"], "| Typ:", file_meta["mimeType"])

        # 2. Lade Dateiinhalt
        if "application/zip" in file_meta["mimeType"]:
            downloaded = drive_service.files().get_media(fileId=file_id).execute()
            with zipfile.ZipFile(io.BytesIO(downloaded)) as zip_ref:
                knowledge = ""
                for file in zip_ref.namelist():
                    if file.endswith((".txt", ".pdf")):
                        with zip_ref.open(file) as f:
                            knowledge += f.read().decode("utf-8", errors="ignore") + "\n\n"
                return knowledge
        else:
            st.error("🔴 Keine ZIP-Datei! MIME-Typ:", file_meta["mimeType"])
            return ""

    except Exception as e:
        st.error(f"🔴 Kritischer Fehler: {str(e)}")
        return ""

# --- Wissen VOR der Bildverarbeitung laden ---
drive_knowledge = load_knowledge_from_drive(drive_service) if "gdrive_creds" in st.secrets else ""

# --- Bild-Upload und Verarbeitung ---
uploaded_file = st.file_uploader(
    "**Choose an exam paper image...**\n\nDrag and drop file here\nLimit 200MB per file - PNG, JPG, JPEG, WEBP, BMP",
    type=["png", "jpg", "jpeg", "webp", "bmp"]
)

if uploaded_file:
    # --- OCR mit Gemini ---
    genai.configure(api_key=st.secrets["gemini_key"])
    model = genai.GenerativeModel("gemini-pro-vision")
    image = Image.open(uploaded_file)
    st.image(image, caption="Hochgeladenes Bild", width=300)
    
    with st.spinner("Extrahiere Text mit Gemini..."):
        response = model.generate_content(["Extrahier den Text aus diesem Bild.", image])
        extracted_text = response.text
        st.write("**Extrahiertes Text:**")
        st.code(extracted_text)

    # --- Antwort mit Claude ---
    if extracted_text:
        client = Anthropic(api_key=st.secrets["claude_key"])
        with st.spinner("Claude denkt nach..."):
            response = client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=4000,
                messages=[
                    {
                        "role": "user",
                        "content": f"""
                        Hier ist eine Accounting-Frage (extrahiert aus einem Bild):\n\n{extracted_text}\n\n
                        Beantworte die Frage präzise auf Deutsch. Nutze falls nötig dieses Hintergrundwissen:\n\n{drive_knowledge}
                        """
                    }
                ]
            )
            st.write("**Antwort von Claude:**")
            st.markdown(response.content[0].text)

# Debug-Option (optional)
with st.expander("🔍 Debug: Geladenes Wissen anzeigen"):
    st.text(drive_knowledge[:1000] + "...")
