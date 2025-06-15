import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PIL import Image
import google.generativeai as genai
from anthropic import Anthropic
import io
import zipfile
import logging

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- UI-Einstellungen ---
st.set_page_config(layout="centered")
st.title("🦊 Koifox-Bot")
st.markdown("""
    *This application uses Google's Gemini for OCR and Anthropic's Claude for answering advanced accounting questions.*  
    *Made with coffee, deep minimal and tiny gummy bears*  
""")

# --- Google Drive-Verbindung (silent) ---
drive_service = None
if "gdrive_creds" in st.secrets:
    try:
        creds = service_account.Credentials.from_service_account_info(
            st.secrets["gdrive_creds"]
        )
        drive_service = build("drive", "v3", credentials=creds)
        
        # Automatische Ordner- und Dateisuche
        try:
            folder = drive_service.files().list(
                q="name='IRW_Bot_Gehirn' and mimeType='application/vnd.google-apps.folder'",
                pageSize=1,
                fields="files(id)"
            ).execute().get('files', [{}])[0]
            
            if folder.get('id'):
                zip_file = drive_service.files().list(
                    q=f"'{folder['id']}' in parents and mimeType='application/zip'",
                    pageSize=1,
                    fields="files(id)"
                ).execute().get('files', [{}])[0]
                
                if zip_file.get('id'):
                    st.session_state.drive_file_id = zip_file['id']
        except Exception as e:
            logger.error(f"Drive-Suche fehlgeschlagen: {str(e)}")
    except Exception as e:
        logger.error(f"Drive-Verbindung fehlgeschlagen: {str(e)}")

# --- Silent Wissen laden ---
if drive_service and hasattr(st.session_state, 'drive_file_id'):
    try:
        downloaded = drive_service.files().get_media(fileId=st.session_state.drive_file_id).execute()
        with zipfile.ZipFile(io.BytesIO(downloaded)) as zip_ref:
            drive_knowledge = "\n\n".join([
                f.read().decode("utf-8", errors="ignore")
                for file in zip_ref.namelist()
                if file.endswith((".txt", ".pdf"))
            ])
        st.session_state.drive_knowledge = drive_knowledge
    except Exception as e:
        logger.error(f"Wissensladung fehlgeschlagen: {str(e)}")
        st.session_state.drive_knowledge = ""

# --- Accounting Expert Prompt ---
ACCOUNTING_PROMPT = """
You are a highly qualified accounting expert with PhD-level knowledge [...] 
[Ihr vollständiger Prompt hier]
"""

# --- Bild-Upload und Verarbeitung ---
uploaded_file = st.file_uploader(
    "**Choose an exam paper image...**\n\nDrag and drop file here\nLimit 200MB per file - PNG, JPG, JPEG, WEBP, BMP",
    type=["png", "jpg", "jpeg", "webp", "bmp"]
)

if uploaded_file:
    try:
        # 1. Dateivalidierung
        try:
            image = Image.open(uploaded_file)
            image.verify()  # Prüft Bildintegrität
            image = Image.open(uploaded_file)  # Neu öffnen nach verify()
            st.image(image, caption="Hochgeladenes Bild", width=300)
        except Exception as e:
            raise ValueError(f"Ungültiges Bildformat: {str(e)}")

        # 2. Gemini OCR Initialisierung
        if "gemini_key" not in st.secrets:
            raise ValueError("Gemini API Key fehlt in den Secrets")
        
        genai.configure(api_key=st.secrets["gemini_key"])
        model = genai.GenerativeModel(
            "gemini-pro-vision",
            generation_config={"temperature": 0.1}
        )
        
        # 3. OCR-Verarbeitung
        with st.spinner("Analysiere Prüfungsdokument..."):
            response = model.generate_content(
                ["Extrahieren Sie den Text präzise aus diesem Prüfungsdokument:", image]
            )
            extracted_text = response.text
        
        # 4. Claude Initialisierung
        if "claude_key" not in st.secrets:
            raise ValueError("Claude API Key fehlt in den Secrets")
        
        client = Anthropic(api_key=st.secrets["claude_key"])
        
        # 5. Experten-Antwort generieren
        if extracted_text:
            with st.spinner("Erstelle Experten-Antwort..."):
                response = client.messages.create(
                    model="claude-3-opus-20240229",
                    max_tokens=4000,
                    messages=[
                        {
                            "role": "system",
                            "content": ACCOUNTING_PROMPT
                        },
                        {
                            "role": "user",
                            "content": f"""
                            <OCR_TEXT>
                            {extracted_text}
                            </OCR_TEXT>
                            
                            Nutze falls verfügbar dieses Hintergrundwissen:
                            {st.session_state.get('drive_knowledge', '')}
                            """
                        }
                    ]
                )
                
                # Antwortformatierung
                answer_content = response.content[0].text
                answer = (answer_content.split("<answer>")[1].split("</answer>")[0].strip() 
                         if "<answer>" in answer_content else answer_content)
                
                st.markdown("### Experten-Antwort:")
                st.markdown(answer)
    
    except Exception as e:
        logger.error(f"Verarbeitungsfehler: {str(e)}", exc_info=True)
        st.error(f"Fehler: {str(e)}")
        
        # Technische Details für Support
        with st.expander("Technische Details (für Support)"):
            st.text(f"Fehlertyp: {type(e).__name__}")
            st.text(f"Fehlermeldung: {str(e)}")
            if hasattr(e, 'response'):
                st.json(e.response.text if e.response else "Keine Response-Daten")
