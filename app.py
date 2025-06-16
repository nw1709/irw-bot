import re  # Fügen Sie dies ganz oben bei den Imports hinzu
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

# --- API Key Validation ---
def validate_keys():
    required_keys = {
        'gemini_key': ('AIza', "Gemini"),
        'claude_key': ('sk-ant', "Claude")
    }
    missing = []
    invalid = []
    
    for key, (prefix, name) in required_keys.items():
        if key not in st.secrets:
            missing.append(name)
        elif not st.secrets[key].startswith(prefix):
            invalid.append(name)
    
    if missing or invalid:
        st.error(f"API Key Problem: Missing {', '.join(missing)} | Invalid {', '.join(invalid)}")
        st.stop()

validate_keys()

# --- UI-Einstellungen ---
st.set_page_config(layout="centered")
st.title("🦊 Koifox-Bot")
st.markdown("""
    *This application uses Google's Gemini for OCR and Anthropic's Claude for answering advanced accounting questions.*  
    *Made with coffee, deep minimal and tiny gummy bears*  
""")

# --- Google Drive-Verbindung ---
drive_service = None
if "gdrive_creds" in st.secrets:
    try:
        creds = service_account.Credentials.from_service_account_info(st.secrets["gdrive_creds"])
        drive_service = build("drive", "v3", credentials=creds)
        
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
        logger.error(f"Drive Error: {str(e)}")

# --- Wissen laden ---
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
        logger.error(f"Knowledge Load Error: {str(e)}")
        st.session_state.drive_knowledge = ""

# --- Gemini 1.5 Flash Konfiguration ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")

# --- Hybrid Accounting Prompt ---
ACCOUNTING_PROMPT = """
Sie sind ein Klausurexperte für das Modul "Internes Rechnungswesen" der Fernuniversität Hagen. Nutzen Sie ALLE verfügbaren Wissensquellen in dieser Priorität:

1. **Primärquellen** (streng verbindlich):
   - Offizielle Modulskripte/Studienbriefe der Fernuniversität Hagen
   - Altklausuren der Fernuniversität Hagen sowie ggf. Lösungshinweise/Lösungen dieser Klausuren

2. **Sekundärquellen**
   - Im Wissen bereitgestellte externe Skripte und Klausurlösungen
   - Standardlehrwerke: Ewert/Wagenhofer, Coenenberg

3. **Verarbeitungsregeln**:
   - Immer zuerst Hagen-Quellen prüfen
   - Bei Widersprüchen: "Laut Einheit X S.Y: [Lösung] (Abweichung zu [andere Quelle] beachten)"
   - Keine Lösungen außerhalb der bereitgestellten Materialien

4. **Antwortformat**:
   Aufgabe [X]: [Lösung]
   Quelle: [Einheit X S.Y / Altklausur WS2022, Aufgabe 3 / Ewert-Wagenhofer S.Z]
   Konsistenzcheck: [✓ Falls Hagen-quellenkongruent / △ Falls abweichend]

5. **Hagen-spezifische Besonderheiten**:
   - Typische Klausurformate: [Mehrstufige DB-Rechnung, Prozesskostenanalyse]
   - Häufige Fallstricke: [Fixkostenproportionalisierung, Verrechnungspreise]
   - Prüfererwartungen: [Formale Genauigkeit > Kreativität]
"""

# --- Bildverarbeitung ---
try:
    uploaded_file = st.file_uploader(
        "**Klausuraufgabe hochladen...**\n\n(PNG/JPG/JPEG, max. 200MB)",
        type=["png", "jpg", "jpeg"],
        key="file_uploader"
    )

    if uploaded_file is not None:
        try:
            # Bild anzeigen (ohne Vorverarbeitung)
            image = Image.open(uploaded_file)
            st.image(image, caption="Hochgeladenes Dokument", use_container_width=True)

            # OCR mit Gemini
            with st.spinner("Analysiere Klausuraufgaben..."):
                response = vision_model.generate_content(
                    [
                        "Extract ALL exam tasks with:",
                        "1. Complete question text",
                        "2. All numbers and options (A/B/C...)",
                        "3. Formulas and tables",
                        "Format: 'TASK X: [Question] | OPTIONS: A)... B)...'",
                        image
                    ],
                    generation_config={
                        "temperature": 0,
                        "max_output_tokens": 4000
                    }
                )
                extracted_text = response.text

            # --- Claude Analyse ---
            if extracted_text:
                client = Anthropic(api_key=st.secrets["claude_key"])
                response = client.messages.create(
                    model="claude-3-opus-20240229",
                    max_tokens=4000,
                    messages=[{
                        "role": "user",
                        "content": f"""
                        {ACCOUNTING_PROMPT}
                        
                        <EXAM_DOCUMENT>
                        {extracted_text}
                        </EXAM_DOCUMENT>
                        
                        <KNOWLEDGE_BASE>
                        {st.session_state.get('drive_knowledge', '')}
                        </KNOWLEDGE_BASE>
                        """
                    }],
                    temperature=0
                )

                # Antwortformatierung
                answer_content = response.content[0].text
                st.markdown("### Lösungen:")
                st.markdown(answer_content)

        except Exception as e:
            st.error(f"Verarbeitungsfehler: {str(e)}")
            logger.error(f"Processing Error: {str(e)}")

except Exception as e:
    st.error(f"Systemfehler: {str(e)}")
    logger.critical(f"System Error: {str(e)}")

# --- Antwortverarbeitung (finale optimierte Version) ---
if 'extracted_text' in locals() or 'extracted_text' in globals():
    if extracted_text:
        try:
            client = Anthropic(api_key=st.secrets["claude_key"])
            response = client.messages.create(
                model="claude-3-opus-20240229",  # Korrekte Schreibweise "model" statt "mode1"
                messages=[{
                    "role": "user",
                    "content": f"""Antworte genau im folgenden Format ohne zusätzlichen Text:

                    Aufgabe [Nr]: [Lösung]
                    Begründung: [1-Satz-Erklärung mit Hagen-Skriptreferenz]

                    Regeln:
                    • Nur Lösungen aus Hagen-Modulmaterialien (Skripte/Altklausuren)
                    • Keine Bestätigungen ('Verstanden...')
                    • Keine Überschriften
                    • Deutsche Fachbegriffe
                    • Keine Wiederholungen
                    • Immer Skriptstelle angeben (z.B. "Hagen-Skript 2023 S.45")"""
                }],
                max_tokens=1000,  # Erhöht für Skriptreferenzen
                temperature=0
            )
            
            # Filtert Bestätigungen und leere Zeilen heraus
            clean_lines = [
                line.replace("TASK", "Aufgabe")  # Englisch -> Deutsch
                for line in response.content[0].text.split('\n')
                if line.strip() and not any(
                    phrase in line for phrase in [
                        "Verstanden", 
                        "I'll", 
                        " format",
                        "###"
                    ]
                )
            ]
            
            st.markdown("\n".join(clean_lines))
            
        except Exception as e:
            st.error(f"Fehler: {str(e)}")
